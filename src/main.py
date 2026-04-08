"""CLI entry point for the ad creative testing agent system."""

from __future__ import annotations

import asyncio
import json
import logging
import sys
from decimal import Decimal
from uuid import UUID

import click

from src.config import get_settings


def _configure_logging() -> None:
    """Set up structured logging based on the configured log level."""
    settings = get_settings()
    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        stream=sys.stdout,
    )


def _get_adapter(platform: str):
    """Return the appropriate adapter for the given platform.

    Falls back to MockAdapter when real API credentials are not configured.
    """
    from src.adapters.mock import MockAdapter

    settings = get_settings()

    if platform == "meta":
        if settings.meta_access_token and not settings.meta_access_token.startswith("placeholder"):
            from src.adapters.meta import MetaAdapter

            return MetaAdapter(
                app_id=settings.meta_app_id,
                app_secret=settings.meta_app_secret,
                access_token=settings.meta_access_token,
                ad_account_id=settings.meta_ad_account_id,
                page_id=settings.meta_page_id,
                landing_page_url=settings.meta_landing_page_url,
            )
    elif platform == "google_ads":
        if settings.google_ads_developer_token and not settings.google_ads_developer_token.startswith("placeholder"):
            from src.adapters.google_ads import GoogleAdsAdapter

            return GoogleAdsAdapter(
                developer_token=settings.google_ads_developer_token,
                client_id=settings.google_ads_client_id,
                client_secret=settings.google_ads_client_secret,
                refresh_token=settings.google_ads_refresh_token,
                customer_id=settings.google_ads_customer_id,
            )

    # Default: mock adapter for development / unrecognized platforms
    click.echo(f"  Using MockAdapter for platform '{platform}' (no real credentials configured)")
    return MockAdapter()


@click.group()
def cli() -> None:
    """Ad creative testing agent — autonomous optimization CLI."""
    _configure_logging()


@cli.command()
@click.option("--campaign-id", required=True, type=str, help="Campaign UUID to optimize.")
@click.option("--no-generate", is_flag=True, default=False, help="Skip generate and deploy phases (metrics-only cycle).")
def run_cycle(campaign_id: str, no_generate: bool) -> None:
    """Run a single optimization cycle for a campaign."""

    async def _run() -> None:
        from sqlalchemy import text as sa_text

        from src.db.engine import _get_session_factory, close_db, get_session, init_db
        from src.services.orchestrator import Orchestrator

        settings = get_settings()
        await init_db()

        # Look up campaign platform to select the right adapter
        async with get_session() as session:
            row = await session.execute(
                sa_text("SELECT platform FROM campaigns WHERE id = :id"),
                {"id": campaign_id},
            )
            result = row.fetchone()
            if not result:
                click.echo(f"Error: Campaign {campaign_id} not found.")
                await close_db()
                return
            platform = str(result[0])

        adapter = _get_adapter(platform)
        session_factory = _get_session_factory()
        orchestrator = Orchestrator(
            adapter=adapter,
            session_factory=session_factory,
            settings=settings,
        )
        report = await orchestrator.run_cycle(UUID(campaign_id), skip_generate=no_generate)
        click.echo(f"Cycle #{report.cycle_number} complete: {report.summary_text}")
        if report.errors:
            for phase, err in report.errors.items():
                click.echo(f"  Error in {phase}: {err[:200]}")
        await close_db()

    asyncio.run(_run())


@cli.command()
@click.option(
    "--file",
    "file_path",
    required=True,
    type=click.Path(exists=True),
    help="Path to gene_pool_seed.json.",
)
def seed_gene_pool(file_path: str) -> None:
    """Seed the gene pool from a JSON file."""

    async def _run() -> None:
        from pathlib import Path

        from src.db.engine import close_db, get_session, init_db
        from src.db.seed import seed_gene_pool as do_seed

        await init_db()
        async with get_session() as session:
            count = await do_seed(session, Path(file_path))
        click.echo(f"Seeded {count} gene pool entries.")
        await close_db()

    asyncio.run(_run())


@cli.command()
@click.option("--name", required=True, help="Campaign name.")
@click.option(
    "--platform",
    required=True,
    type=click.Choice(["meta", "google_ads", "tiktok", "linkedin"]),
    help="Ad platform.",
)
@click.option("--daily-budget", required=True, type=float, help="Daily budget in dollars.")
@click.option("--max-variants", default=10, type=int, help="Max concurrent variants.")
@click.option("--platform-campaign-id", default=None, type=str, help="Platform-side campaign ID.")
def create_campaign(
    name: str,
    platform: str,
    daily_budget: float,
    max_variants: int,
    platform_campaign_id: str | None,
) -> None:
    """Create a new campaign."""

    async def _run() -> None:
        from src.db.engine import close_db, get_session, init_db
        from src.db.tables import Campaign, PlatformType

        await init_db()
        async with get_session() as session:
            campaign = Campaign(
                name=name,
                platform=PlatformType(platform),
                platform_campaign_id=platform_campaign_id,
                daily_budget=Decimal(str(daily_budget)),
                max_concurrent_variants=max_variants,
            )
            session.add(campaign)
            await session.flush()
            click.echo(f"Created campaign: {campaign.id} ({name})")
        await close_db()

    asyncio.run(_run())


@cli.command()
def health_check() -> None:
    """Check database connectivity and system health."""

    async def _run() -> None:
        from sqlalchemy import text as sa_text

        from src.db.engine import close_db, get_session, init_db

        await init_db()
        click.echo("Database connection: OK")

        async with get_session() as session:
            # Check table counts
            tables = ["gene_pool", "campaigns", "variants", "deployments", "metrics"]
            for table in tables:
                row = await session.execute(sa_text(f"SELECT COUNT(*) FROM {table}"))
                count = row.scalar_one()
                click.echo(f"  {table}: {count} rows")

            # Check TimescaleDB extension
            row = await session.execute(
                sa_text("SELECT extversion FROM pg_extension WHERE extname = 'timescaledb'")
            )
            ts_version = row.scalar_one_or_none()
            if ts_version:
                click.echo(f"  TimescaleDB: v{ts_version}")
            else:
                click.echo("  TimescaleDB: NOT INSTALLED")

        await close_db()

    asyncio.run(_run())


@cli.command()
@click.option("--campaign-id", required=True, type=str, help="Campaign UUID.")
@click.option("--send-email", is_flag=True, default=False, help="Send report via email.")
def weekly_report(campaign_id: str, send_email: bool) -> None:
    """Generate and send a weekly report for a campaign."""

    async def _run() -> None:
        from datetime import date, datetime, timedelta, timezone

        from sqlalchemy import text as sa_text

        from src.db.engine import close_db, get_session, init_db
        from src.models.analysis import ElementInsight, InteractionInsight
        from src.models.reports import FunnelStage, VariantSummary, WeeklyReport

        settings = get_settings()
        await init_db()

        async with get_session() as session:
            # Get campaign name
            campaign_row = await session.execute(
                sa_text("SELECT name FROM campaigns WHERE id = :id"),
                {"id": campaign_id},
            )
            campaign_result = campaign_row.fetchone()
            if not campaign_result:
                click.echo(f"Error: Campaign {campaign_id} not found.")
                await close_db()
                return
            campaign_name = str(campaign_result[0])

            # Previous full week: Monday through Sunday
            today = date.today()
            # today.weekday(): Mon=0, Sun=6
            # Previous Sunday = today - (weekday + 1)
            week_end = today - timedelta(days=today.weekday() + 1)  # last Sunday
            week_start = week_end - timedelta(days=6)               # Monday before that

            week_start_ts = datetime(week_start.year, week_start.month, week_start.day, tzinfo=timezone.utc)
            week_end_ts = datetime(week_end.year, week_end.month, week_end.day, tzinfo=timezone.utc) + timedelta(days=1)  # midnight after Sunday

            cycles_row = await session.execute(
                sa_text("""
                    SELECT cycle_number, phase, variants_launched, variants_paused,
                           variants_promoted, summary_text, started_at
                    FROM test_cycles
                    WHERE campaign_id = :id
                      AND started_at >= :ws AND started_at < :we
                    ORDER BY cycle_number DESC
                """),
                {"id": campaign_id, "ws": week_start_ts, "we": week_end_ts},
            )
            cycles = cycles_row.fetchall()

            if not cycles:
                click.echo(f"No cycles found for week {week_start} to {week_end} for campaign {campaign_id}.")
                await close_db()
                return

            # Aggregate full-funnel metrics for the previous week
            metrics_row = await session.execute(
                sa_text("""
                    SELECT COALESCE(SUM(m.impressions), 0),
                           COALESCE(SUM(m.clicks), 0),
                           COALESCE(SUM(m.conversions), 0),
                           COALESCE(SUM(m.spend), 0),
                           COALESCE(SUM(m.reach), 0),
                           COALESCE(SUM(m.video_views_3s), 0),
                           COALESCE(SUM(m.video_views_15s), 0),
                           COALESCE(SUM(m.thruplays), 0),
                           COALESCE(SUM(m.link_clicks), 0),
                           COALESCE(SUM(m.landing_page_views), 0),
                           COALESCE(SUM(m.add_to_carts), 0),
                           COALESCE(SUM(m.purchases), 0),
                           COALESCE(SUM(m.purchase_value), 0)
                    FROM metrics m
                    JOIN variants v ON v.id = m.variant_id
                    WHERE v.campaign_id = :id
                      AND m.recorded_at >= :ws AND m.recorded_at < :we
                """),
                {"id": campaign_id, "ws": week_start_ts, "we": week_end_ts},
            )
            m = metrics_row.fetchone()
            total_impressions = int(m[0])
            total_clicks = int(m[1])
            total_conversions = int(m[2])
            total_spend = Decimal(str(m[3]))
            total_reach = int(m[4])
            total_video_views_3s = int(m[5])
            total_video_views_15s = int(m[6])
            total_thruplays = int(m[7])
            total_link_clicks = int(m[8])
            total_landing_page_views = int(m[9])
            total_add_to_carts = int(m[10])
            total_purchases = int(m[11])
            total_purchase_value = Decimal(str(m[12]))

            # Derived aggregates
            avg_ctr = Decimal(str(total_clicks / total_impressions)) if total_impressions > 0 else Decimal("0")
            avg_cpa = Decimal(str(float(total_spend) / total_conversions)) if total_conversions > 0 else None
            avg_hook_rate = Decimal(str(total_video_views_3s / total_impressions)) if total_impressions > 0 else Decimal("0")
            avg_hold_rate = Decimal(str(total_video_views_15s / total_video_views_3s)) if total_video_views_3s > 0 else Decimal("0")
            avg_cpm = Decimal(str((float(total_spend) / total_impressions) * 1000)) if total_impressions > 0 else Decimal("0")
            avg_frequency = Decimal(str(total_impressions / total_reach)) if total_reach > 0 else Decimal("0")
            avg_roas = Decimal(str(float(total_purchase_value) / float(total_spend))) if float(total_spend) > 0 and float(total_purchase_value) > 0 else None
            avg_cost_per_purchase = Decimal(str(float(total_spend) / total_purchases)) if total_purchases > 0 else None

            # Build funnel stages
            spend_f = float(total_spend)
            funnel_stages = [
                FunnelStage(stage_name="Impressions", value=total_impressions, rate=None,
                            cost_per=Decimal(str(round(spend_f / total_impressions * 1000, 2))) if total_impressions > 0 else None),
                FunnelStage(stage_name="Reach", value=total_reach,
                            rate=None, cost_per=Decimal(str(round(spend_f / total_reach * 1000, 2))) if total_reach > 0 else None),
            ]
            if total_video_views_3s > 0:
                funnel_stages.append(FunnelStage(
                    stage_name="Video Views (3s)", value=total_video_views_3s,
                    rate=Decimal(str(round(total_video_views_3s / total_impressions, 4))) if total_impressions > 0 else None,
                    cost_per=Decimal(str(round(spend_f / total_video_views_3s, 2))) if total_video_views_3s > 0 else None,
                ))
            if total_video_views_15s > 0:
                funnel_stages.append(FunnelStage(
                    stage_name="Video Views (15s)", value=total_video_views_15s,
                    rate=Decimal(str(round(total_video_views_15s / total_video_views_3s, 4))) if total_video_views_3s > 0 else None,
                    cost_per=Decimal(str(round(spend_f / total_video_views_15s, 2))) if total_video_views_15s > 0 else None,
                ))
            if total_link_clicks > 0:
                funnel_stages.append(FunnelStage(
                    stage_name="Link Clicks", value=total_link_clicks,
                    rate=Decimal(str(round(total_link_clicks / total_impressions, 4))) if total_impressions > 0 else None,
                    cost_per=Decimal(str(round(spend_f / total_link_clicks, 2))),
                ))
            if total_landing_page_views > 0:
                funnel_stages.append(FunnelStage(
                    stage_name="Landing Page Views", value=total_landing_page_views,
                    rate=Decimal(str(round(total_landing_page_views / total_link_clicks, 4))) if total_link_clicks > 0 else None,
                    cost_per=Decimal(str(round(spend_f / total_landing_page_views, 2))),
                ))
            if total_add_to_carts > 0:
                funnel_stages.append(FunnelStage(
                    stage_name="Add to Carts", value=total_add_to_carts,
                    rate=Decimal(str(round(total_add_to_carts / total_landing_page_views, 4))) if total_landing_page_views > 0 else None,
                    cost_per=Decimal(str(round(spend_f / total_add_to_carts, 2))),
                ))
            if total_purchases > 0:
                funnel_stages.append(FunnelStage(
                    stage_name="Purchases", value=total_purchases,
                    rate=Decimal(str(round(total_purchases / total_add_to_carts, 4))) if total_add_to_carts > 0 else None,
                    cost_per=Decimal(str(round(spend_f / total_purchases, 2))),
                ))

            # Variant leaderboard — full-funnel query
            variant_row = await session.execute(
                sa_text("""
                    SELECT v.id, v.variant_code, v.status,
                           COALESCE(m.impressions, 0), COALESCE(m.clicks, 0),
                           COALESCE(m.conversions, 0), COALESCE(m.spend, 0),
                           COALESCE(m.reach, 0), COALESCE(m.video_views_3s, 0),
                           COALESCE(m.video_views_15s, 0), COALESCE(m.thruplays, 0),
                           COALESCE(m.link_clicks, 0), COALESCE(m.landing_page_views, 0),
                           COALESCE(m.add_to_carts, 0), COALESCE(m.purchases, 0),
                           COALESCE(m.purchase_value, 0)
                    FROM variants v
                    LEFT JOIN LATERAL (
                        SELECT SUM(impressions) AS impressions, SUM(clicks) AS clicks,
                               SUM(conversions) AS conversions, SUM(spend) AS spend,
                               SUM(reach) AS reach, SUM(video_views_3s) AS video_views_3s,
                               SUM(video_views_15s) AS video_views_15s, SUM(thruplays) AS thruplays,
                               SUM(link_clicks) AS link_clicks, SUM(landing_page_views) AS landing_page_views,
                               SUM(add_to_carts) AS add_to_carts, SUM(purchases) AS purchases,
                               SUM(purchase_value) AS purchase_value
                        FROM metrics WHERE variant_id = v.id
                          AND recorded_at >= :ws AND recorded_at < :we
                    ) m ON TRUE
                    WHERE v.campaign_id = :id AND v.status IN ('active', 'winner', 'paused')
                    ORDER BY CASE WHEN COALESCE(m.purchases, 0) > 0 AND COALESCE(m.spend, 0) > 0
                                  THEN COALESCE(m.purchase_value, 0)::NUMERIC / m.spend
                                  WHEN COALESCE(m.impressions, 0) > 0
                                  THEN COALESCE(m.clicks, 0)::NUMERIC / m.impressions
                                  ELSE 0 END DESC
                """),
                {"id": campaign_id, "ws": week_start_ts, "we": week_end_ts},
            )
            variant_rows = variant_row.fetchall()

            def _make_variant_summary(row) -> VariantSummary:
                imps = int(row[3])
                clicks = int(row[4])
                convs = int(row[5])
                spend = Decimal(str(row[6]))
                reach = int(row[7])
                vv3s = int(row[8])
                vv15s = int(row[9])
                thruplays = int(row[10])
                lc = int(row[11])
                lpv = int(row[12])
                atc = int(row[13])
                purch = int(row[14])
                pv = Decimal(str(row[15]))

                ctr = Decimal(str(clicks / imps)) if imps > 0 else Decimal("0")
                cpa = Decimal(str(float(spend) / convs)) if convs > 0 else None
                hr = Decimal(str(vv3s / imps)) if imps > 0 else Decimal("0")
                hold = Decimal(str(vv15s / vv3s)) if vv3s > 0 else Decimal("0")
                cpp = Decimal(str(float(spend) / purch)) if purch > 0 else None
                roas = Decimal(str(float(pv) / float(spend))) if float(spend) > 0 and float(pv) > 0 else None

                return VariantSummary(
                    variant_id=row[0],
                    variant_code=str(row[1]),
                    status=str(row[2]),
                    impressions=imps,
                    clicks=clicks,
                    conversions=convs,
                    spend=spend,
                    ctr=ctr,
                    cpa=cpa,
                    reach=reach,
                    video_views_3s=vv3s,
                    video_views_15s=vv15s,
                    thruplays=thruplays,
                    link_clicks=lc,
                    landing_page_views=lpv,
                    add_to_carts=atc,
                    purchases=purch,
                    purchase_value=pv,
                    hook_rate=hr,
                    hold_rate=hold,
                    cost_per_purchase=cpp,
                    roas=roas,
                )

            all_variants = [_make_variant_summary(r) for r in variant_rows]
            best_variant = all_variants[0] if all_variants else None
            worst_variant = all_variants[-1] if len(all_variants) > 1 else None

            # Element rankings — include new funnel columns
            rankings_row = await session.execute(
                sa_text("""
                    SELECT slot_name, slot_value, avg_ctr, avg_cpa, variants_tested,
                           best_ctr, worst_ctr, total_impressions, total_conversions, confidence,
                           avg_hook_rate, avg_roas, best_hook_rate, best_cpa, total_purchases
                    FROM element_performance
                    WHERE campaign_id = :id AND variants_tested >= 1
                    ORDER BY avg_ctr DESC NULLS LAST
                    LIMIT 20
                """),
                {"id": campaign_id},
            )
            rankings = rankings_row.fetchall()
            top_elements = [
                ElementInsight(
                    slot_name=str(r[0]),
                    slot_value=str(r[1]),
                    avg_ctr=Decimal(str(r[2] or 0)),
                    avg_cpa=Decimal(str(r[3])) if r[3] else None,
                    variants_tested=int(r[4]),
                    best_ctr=Decimal(str(r[5])) if r[5] else None,
                    worst_ctr=Decimal(str(r[6])) if r[6] else None,
                    total_impressions=int(r[7]),
                    total_conversions=int(r[8]),
                    confidence=Decimal(str(r[9])) if r[9] else None,
                    avg_hook_rate=Decimal(str(r[10])) if r[10] else None,
                    avg_roas=Decimal(str(r[11])) if r[11] else None,
                    best_hook_rate=Decimal(str(r[12])) if r[12] else None,
                    best_cpa=Decimal(str(r[13])) if r[13] else None,
                    total_purchases=int(r[14]) if r[14] else 0,
                )
                for r in rankings
            ]

            # Element interactions
            interactions_row = await session.execute(
                sa_text("""
                    SELECT slot_a_name, slot_a_value, slot_b_name, slot_b_value,
                           variants_tested, combined_avg_ctr, solo_a_avg_ctr,
                           solo_b_avg_ctr, interaction_lift, confidence
                    FROM element_interactions
                    WHERE campaign_id = :id
                    ORDER BY ABS(interaction_lift) DESC NULLS LAST
                    LIMIT 10
                """),
                {"id": campaign_id},
            )
            interactions = interactions_row.fetchall()
            top_interactions = [
                InteractionInsight(
                    slot_a_name=str(r[0]),
                    slot_a_value=str(r[1]),
                    slot_b_name=str(r[2]),
                    slot_b_value=str(r[3]),
                    variants_tested=int(r[4]),
                    combined_avg_ctr=Decimal(str(r[5] or 0)),
                    solo_a_avg_ctr=Decimal(str(r[6])) if r[6] else None,
                    solo_b_avg_ctr=Decimal(str(r[7])) if r[7] else None,
                    interaction_lift=Decimal(str(r[8])) if r[8] else None,
                    confidence=Decimal(str(r[9])) if r[9] else None,
                )
                for r in interactions
            ]

            total_launched = sum(c[2] or 0 for c in cycles)
            total_paused = sum(c[3] or 0 for c in cycles)
            total_retired = 0

            # Build the WeeklyReport
            report = WeeklyReport(
                campaign_id=UUID(campaign_id),
                campaign_name=campaign_name,
                week_start=week_start,
                week_end=week_end,
                total_spend=total_spend,
                total_impressions=total_impressions,
                total_clicks=total_clicks,
                total_conversions=total_conversions,
                avg_ctr=avg_ctr,
                avg_cpa=avg_cpa,
                total_reach=total_reach,
                total_video_views_3s=total_video_views_3s,
                total_video_views_15s=total_video_views_15s,
                total_thruplays=total_thruplays,
                total_link_clicks=total_link_clicks,
                total_landing_page_views=total_landing_page_views,
                total_add_to_carts=total_add_to_carts,
                total_purchases=total_purchases,
                total_purchase_value=total_purchase_value,
                avg_hook_rate=avg_hook_rate,
                avg_hold_rate=avg_hold_rate,
                avg_cpm=avg_cpm,
                avg_frequency=avg_frequency,
                avg_roas=avg_roas,
                avg_cost_per_purchase=avg_cost_per_purchase,
                funnel_stages=funnel_stages,
                best_variant=best_variant,
                worst_variant=worst_variant,
                all_variants=all_variants,
                top_elements=top_elements,
                top_interactions=top_interactions,
                cycles_run=len(cycles),
                variants_launched=total_launched,
                variants_retired=total_retired,
                summary_text="Weekly optimization summary for " + campaign_name,
            )

        # Print to console
        click.echo(f"\n{'='*60}")
        click.echo(f"WEEKLY REPORT — {campaign_name}")
        click.echo(f"{'='*60}")
        click.echo(f"Period: {week_start} to {week_end}")
        click.echo(f"Cycles completed: {len(cycles)}")
        click.echo(f"Variants launched: {total_launched}")
        click.echo(f"Variants paused: {total_paused}")
        click.echo(f"\nFull-Funnel Metrics:")
        click.echo(f"  Impressions: {total_impressions:,}")
        click.echo(f"  Reach: {total_reach:,}")
        click.echo(f"  Video Views (3s): {total_video_views_3s:,}  Hook Rate: {avg_hook_rate:.1%}")
        click.echo(f"  Video Views (15s): {total_video_views_15s:,}  Hold Rate: {avg_hold_rate:.1%}")
        click.echo(f"  Link Clicks: {total_link_clicks:,}  CTR: {avg_ctr:.2%}")
        click.echo(f"  Landing Page Views: {total_landing_page_views:,}")
        click.echo(f"  Add to Carts: {total_add_to_carts:,}")
        click.echo(f"  Purchases: {total_purchases:,}")
        click.echo(f"  Revenue: ${total_purchase_value:,.2f}")
        click.echo(f"\nEfficiency:")
        click.echo(f"  Spend: ${total_spend:,.2f}")
        click.echo(f"  CPM: ${avg_cpm:,.2f}")
        click.echo(f"  CPA: {'${:,.2f}'.format(avg_cpa) if avg_cpa else 'N/A'}")
        click.echo(f"  Cost/Purchase: {'${:,.2f}'.format(avg_cost_per_purchase) if avg_cost_per_purchase else 'N/A'}")
        click.echo(f"  ROAS: {'{:.2f}x'.format(avg_roas) if avg_roas else 'N/A'}")
        click.echo(f"  Frequency: {avg_frequency:.1f}")

        if best_variant:
            roas_str = f"ROAS {best_variant.roas:.2f}x" if best_variant.roas else f"CTR {best_variant.ctr:.2%}"
            click.echo(f"\nBest: {best_variant.variant_code} — {roas_str}")
        if worst_variant:
            roas_str = f"ROAS {worst_variant.roas:.2f}x" if worst_variant.roas else f"CTR {worst_variant.ctr:.2%}"
            click.echo(f"Worst: {worst_variant.variant_code} — {roas_str}")

        if top_elements:
            click.echo(f"\nTop Elements:")
            for el in top_elements[:10]:
                roas_str = f" ROAS {el.avg_roas:.2f}x" if el.avg_roas else ""
                click.echo(f"  {el.slot_name}: {el.slot_value} — CTR {el.avg_ctr:.2%}{roas_str} ({el.variants_tested} variants)")

        # Send email if requested
        if send_email:
            if not settings.sendgrid_api_key or settings.sendgrid_api_key.startswith("placeholder"):
                click.echo("\nError: SENDGRID_API_KEY not configured in .env")
            else:
                from src.reports.email import EmailReporter

                reporter = EmailReporter(
                    api_key=settings.sendgrid_api_key,
                    from_email=settings.report_email_from,
                    to_email=settings.report_email_to,
                )
                success = await reporter.send_weekly_report(report)
                if success:
                    click.echo(f"\nEmail report sent to {settings.report_email_to}")
                else:
                    click.echo("\nFailed to send email report. Check logs.")

        # Send via Slack if configured
        if settings.slack_webhook_url and not settings.slack_webhook_url.startswith("https://hooks.slack.com/services/PLACEHOLDER"):
            from src.reports.slack import SlackReporter

            slack = SlackReporter(webhook_url=settings.slack_webhook_url)
            summary = f"Weekly: {len(cycles)} cycles, {total_launched} launched, {total_paused} paused"
            await slack.send_cycle_report(
                campaign_name=campaign_name,
                cycle_number=0,
                summary=summary,
                actions=[],
            )
            click.echo("\nSlack report sent.")

        # Generate static HTML report
        from src.reports.web import render_weekly_report as render_weekly_html, render_index

        week_label = f"{week_start.isocalendar()[0]}-W{week_start.isocalendar()[1]:02d}"
        html_path = render_weekly_html(report, campaign_name, week_label)
        click.echo(f"\nWeb report: {html_path}")

        # Update index
        from pathlib import Path as _Path

        public_dir = _Path(settings.report_output_dir)
        daily_dates = sorted(
            [p.stem for p in (public_dir / "daily").glob("*.html")] if (public_dir / "daily").exists() else [],
            reverse=True,
        )
        weekly_labels = sorted(
            [p.stem for p in (public_dir / "weekly").glob("*.html")],
            reverse=True,
        )
        render_index(daily_dates, weekly_labels)

        await close_db()

    asyncio.run(_run())


@cli.command()
@click.option("--campaign-id", required=True, type=str, help="Campaign UUID.")
@click.option("--send-email/--no-send-email", default=True, help="Send report via email (default: True).")
@click.option("--report-date", default=None, type=str, help="Date to report on (YYYY-MM-DD). Defaults to yesterday.")
def daily_report(campaign_id: str, send_email: bool, report_date: str | None) -> None:
    """Generate and send a daily performance report for a campaign.

    Reports on a single calendar day (defaults to yesterday).
    """

    async def _run() -> None:
        from datetime import date, datetime, timedelta, timezone

        from sqlalchemy import text as sa_text

        from src.db.engine import close_db, get_session, init_db
        from src.models.analysis import ElementInsight, InteractionInsight
        from src.models.reports import FunnelStage, VariantSummary, WeeklyReport

        settings = get_settings()
        await init_db()

        # Report on a single calendar day — yesterday by default
        if report_date:
            report_day = date.fromisoformat(report_date)
        else:
            report_day = date.today() - timedelta(days=1)

        day_start = datetime(report_day.year, report_day.month, report_day.day, tzinfo=timezone.utc)
        day_end = day_start + timedelta(days=1)

        async with get_session() as session:
            # Get campaign name
            campaign_row = await session.execute(
                sa_text("SELECT name FROM campaigns WHERE id = :id"),
                {"id": campaign_id},
            )
            campaign_result = campaign_row.fetchone()
            if not campaign_result:
                click.echo(f"Error: Campaign {campaign_id} not found.")
                await close_db()
                return
            campaign_name = str(campaign_result[0])

            # Check for cycles on this day
            cycles_row = await session.execute(
                sa_text("""
                    SELECT cycle_number, phase, variants_launched, variants_paused,
                           variants_promoted, summary_text, started_at
                    FROM test_cycles
                    WHERE campaign_id = :id
                      AND started_at >= :day_start AND started_at < :day_end
                    ORDER BY cycle_number DESC
                """),
                {"id": campaign_id, "day_start": day_start, "day_end": day_end},
            )
            cycles = cycles_row.fetchall()

            # Aggregate full-funnel metrics for the calendar day
            metrics_row = await session.execute(
                sa_text("""
                    SELECT COALESCE(SUM(m.impressions), 0),
                           COALESCE(SUM(m.clicks), 0),
                           COALESCE(SUM(m.conversions), 0),
                           COALESCE(SUM(m.spend), 0),
                           COALESCE(SUM(m.reach), 0),
                           COALESCE(SUM(m.video_views_3s), 0),
                           COALESCE(SUM(m.video_views_15s), 0),
                           COALESCE(SUM(m.thruplays), 0),
                           COALESCE(SUM(m.link_clicks), 0),
                           COALESCE(SUM(m.landing_page_views), 0),
                           COALESCE(SUM(m.add_to_carts), 0),
                           COALESCE(SUM(m.purchases), 0),
                           COALESCE(SUM(m.purchase_value), 0)
                    FROM metrics m
                    JOIN variants v ON v.id = m.variant_id
                    WHERE v.campaign_id = :id
                      AND m.recorded_at >= :day_start AND m.recorded_at < :day_end
                """),
                {"id": campaign_id, "day_start": day_start, "day_end": day_end},
            )
            m = metrics_row.fetchone()
            total_impressions = int(m[0])
            total_clicks = int(m[1])
            total_conversions = int(m[2])
            total_spend = Decimal(str(m[3]))
            total_reach = int(m[4])
            total_video_views_3s = int(m[5])
            total_video_views_15s = int(m[6])
            total_thruplays = int(m[7])
            total_link_clicks = int(m[8])
            total_landing_page_views = int(m[9])
            total_add_to_carts = int(m[10])
            total_purchases = int(m[11])
            total_purchase_value = Decimal(str(m[12]))

            # Derived aggregates
            avg_ctr = Decimal(str(total_clicks / total_impressions)) if total_impressions > 0 else Decimal("0")
            avg_cpa = Decimal(str(float(total_spend) / total_conversions)) if total_conversions > 0 else None
            avg_hook_rate = Decimal(str(total_video_views_3s / total_impressions)) if total_impressions > 0 else Decimal("0")
            avg_hold_rate = Decimal(str(total_video_views_15s / total_video_views_3s)) if total_video_views_3s > 0 else Decimal("0")
            avg_cpm = Decimal(str((float(total_spend) / total_impressions) * 1000)) if total_impressions > 0 else Decimal("0")
            avg_frequency = Decimal(str(total_impressions / total_reach)) if total_reach > 0 else Decimal("0")
            avg_roas = Decimal(str(float(total_purchase_value) / float(total_spend))) if float(total_spend) > 0 and float(total_purchase_value) > 0 else None
            avg_cost_per_purchase = Decimal(str(float(total_spend) / total_purchases)) if total_purchases > 0 else None

            # Build funnel stages
            spend_f = float(total_spend)
            funnel_stages = [
                FunnelStage(stage_name="Impressions", value=total_impressions, rate=None,
                            cost_per=Decimal(str(round(spend_f / total_impressions * 1000, 2))) if total_impressions > 0 else None),
                FunnelStage(stage_name="Reach", value=total_reach,
                            rate=None, cost_per=Decimal(str(round(spend_f / total_reach * 1000, 2))) if total_reach > 0 else None),
            ]
            if total_video_views_3s > 0:
                funnel_stages.append(FunnelStage(
                    stage_name="Video Views (3s)", value=total_video_views_3s,
                    rate=Decimal(str(round(total_video_views_3s / total_impressions, 4))) if total_impressions > 0 else None,
                    cost_per=Decimal(str(round(spend_f / total_video_views_3s, 2))) if total_video_views_3s > 0 else None,
                ))
            if total_video_views_15s > 0:
                funnel_stages.append(FunnelStage(
                    stage_name="Video Views (15s)", value=total_video_views_15s,
                    rate=Decimal(str(round(total_video_views_15s / total_video_views_3s, 4))) if total_video_views_3s > 0 else None,
                    cost_per=Decimal(str(round(spend_f / total_video_views_15s, 2))) if total_video_views_15s > 0 else None,
                ))
            if total_link_clicks > 0:
                funnel_stages.append(FunnelStage(
                    stage_name="Link Clicks", value=total_link_clicks,
                    rate=Decimal(str(round(total_link_clicks / total_impressions, 4))) if total_impressions > 0 else None,
                    cost_per=Decimal(str(round(spend_f / total_link_clicks, 2))),
                ))
            if total_landing_page_views > 0:
                funnel_stages.append(FunnelStage(
                    stage_name="Landing Page Views", value=total_landing_page_views,
                    rate=Decimal(str(round(total_landing_page_views / total_link_clicks, 4))) if total_link_clicks > 0 else None,
                    cost_per=Decimal(str(round(spend_f / total_landing_page_views, 2))),
                ))
            if total_add_to_carts > 0:
                funnel_stages.append(FunnelStage(
                    stage_name="Add to Carts", value=total_add_to_carts,
                    rate=Decimal(str(round(total_add_to_carts / total_landing_page_views, 4))) if total_landing_page_views > 0 else None,
                    cost_per=Decimal(str(round(spend_f / total_add_to_carts, 2))),
                ))
            if total_purchases > 0:
                funnel_stages.append(FunnelStage(
                    stage_name="Purchases", value=total_purchases,
                    rate=Decimal(str(round(total_purchases / total_add_to_carts, 4))) if total_add_to_carts > 0 else None,
                    cost_per=Decimal(str(round(spend_f / total_purchases, 2))),
                ))

            # Variant leaderboard — full-funnel query
            variant_row = await session.execute(
                sa_text("""
                    SELECT v.id, v.variant_code, v.status,
                           COALESCE(m.impressions, 0), COALESCE(m.clicks, 0),
                           COALESCE(m.conversions, 0), COALESCE(m.spend, 0),
                           COALESCE(m.reach, 0), COALESCE(m.video_views_3s, 0),
                           COALESCE(m.video_views_15s, 0), COALESCE(m.thruplays, 0),
                           COALESCE(m.link_clicks, 0), COALESCE(m.landing_page_views, 0),
                           COALESCE(m.add_to_carts, 0), COALESCE(m.purchases, 0),
                           COALESCE(m.purchase_value, 0)
                    FROM variants v
                    LEFT JOIN LATERAL (
                        SELECT SUM(impressions) AS impressions, SUM(clicks) AS clicks,
                               SUM(conversions) AS conversions, SUM(spend) AS spend,
                               SUM(reach) AS reach, SUM(video_views_3s) AS video_views_3s,
                               SUM(video_views_15s) AS video_views_15s, SUM(thruplays) AS thruplays,
                               SUM(link_clicks) AS link_clicks, SUM(landing_page_views) AS landing_page_views,
                               SUM(add_to_carts) AS add_to_carts, SUM(purchases) AS purchases,
                               SUM(purchase_value) AS purchase_value
                        FROM metrics WHERE variant_id = v.id
                          AND recorded_at >= :day_start AND recorded_at < :day_end
                    ) m ON TRUE
                    WHERE v.campaign_id = :id AND v.status IN ('active', 'winner', 'paused')
                    ORDER BY CASE WHEN COALESCE(m.purchases, 0) > 0 AND COALESCE(m.spend, 0) > 0
                                  THEN COALESCE(m.purchase_value, 0)::NUMERIC / m.spend
                                  WHEN COALESCE(m.impressions, 0) > 0
                                  THEN COALESCE(m.clicks, 0)::NUMERIC / m.impressions
                                  ELSE 0 END DESC
                """),
                {"id": campaign_id, "day_start": day_start, "day_end": day_end},
            )
            variant_rows = variant_row.fetchall()

            def _make_variant_summary(row) -> VariantSummary:
                imps = int(row[3])
                clicks = int(row[4])
                convs = int(row[5])
                spend = Decimal(str(row[6]))
                reach = int(row[7])
                vv3s = int(row[8])
                vv15s = int(row[9])
                thruplays = int(row[10])
                lc = int(row[11])
                lpv = int(row[12])
                atc = int(row[13])
                purch = int(row[14])
                pv = Decimal(str(row[15]))

                ctr = Decimal(str(clicks / imps)) if imps > 0 else Decimal("0")
                cpa = Decimal(str(float(spend) / convs)) if convs > 0 else None
                hr = Decimal(str(vv3s / imps)) if imps > 0 else Decimal("0")
                hold = Decimal(str(vv15s / vv3s)) if vv3s > 0 else Decimal("0")
                cpp = Decimal(str(float(spend) / purch)) if purch > 0 else None
                roas = Decimal(str(float(pv) / float(spend))) if float(spend) > 0 and float(pv) > 0 else None

                return VariantSummary(
                    variant_id=row[0],
                    variant_code=str(row[1]),
                    status=str(row[2]),
                    impressions=imps,
                    clicks=clicks,
                    conversions=convs,
                    spend=spend,
                    ctr=ctr,
                    cpa=cpa,
                    reach=reach,
                    video_views_3s=vv3s,
                    video_views_15s=vv15s,
                    thruplays=thruplays,
                    link_clicks=lc,
                    landing_page_views=lpv,
                    add_to_carts=atc,
                    purchases=purch,
                    purchase_value=pv,
                    hook_rate=hr,
                    hold_rate=hold,
                    cost_per_purchase=cpp,
                    roas=roas,
                )

            all_variants = [_make_variant_summary(r) for r in variant_rows]
            best_variant = all_variants[0] if all_variants else None
            worst_variant = all_variants[-1] if len(all_variants) > 1 else None

            # Element rankings
            rankings_row = await session.execute(
                sa_text("""
                    SELECT slot_name, slot_value, avg_ctr, avg_cpa, variants_tested,
                           best_ctr, worst_ctr, total_impressions, total_conversions, confidence,
                           avg_hook_rate, avg_roas, best_hook_rate, best_cpa, total_purchases
                    FROM element_performance
                    WHERE campaign_id = :id AND variants_tested >= 1
                    ORDER BY avg_ctr DESC NULLS LAST
                    LIMIT 20
                """),
                {"id": campaign_id},
            )
            rankings = rankings_row.fetchall()
            top_elements = [
                ElementInsight(
                    slot_name=str(r[0]),
                    slot_value=str(r[1]),
                    avg_ctr=Decimal(str(r[2] or 0)),
                    avg_cpa=Decimal(str(r[3])) if r[3] else None,
                    variants_tested=int(r[4]),
                    best_ctr=Decimal(str(r[5])) if r[5] else None,
                    worst_ctr=Decimal(str(r[6])) if r[6] else None,
                    total_impressions=int(r[7]),
                    total_conversions=int(r[8]),
                    confidence=Decimal(str(r[9])) if r[9] else None,
                    avg_hook_rate=Decimal(str(r[10])) if r[10] else None,
                    avg_roas=Decimal(str(r[11])) if r[11] else None,
                    best_hook_rate=Decimal(str(r[12])) if r[12] else None,
                    best_cpa=Decimal(str(r[13])) if r[13] else None,
                    total_purchases=int(r[14]) if r[14] else 0,
                )
                for r in rankings
            ]

            # Element interactions
            interactions_row = await session.execute(
                sa_text("""
                    SELECT slot_a_name, slot_a_value, slot_b_name, slot_b_value,
                           variants_tested, combined_avg_ctr, solo_a_avg_ctr,
                           solo_b_avg_ctr, interaction_lift, confidence
                    FROM element_interactions
                    WHERE campaign_id = :id
                    ORDER BY ABS(interaction_lift) DESC NULLS LAST
                    LIMIT 10
                """),
                {"id": campaign_id},
            )
            interactions = interactions_row.fetchall()
            top_interactions = [
                InteractionInsight(
                    slot_a_name=str(r[0]),
                    slot_a_value=str(r[1]),
                    slot_b_name=str(r[2]),
                    slot_b_value=str(r[3]),
                    variants_tested=int(r[4]),
                    combined_avg_ctr=Decimal(str(r[5] or 0)),
                    solo_a_avg_ctr=Decimal(str(r[6])) if r[6] else None,
                    solo_b_avg_ctr=Decimal(str(r[7])) if r[7] else None,
                    interaction_lift=Decimal(str(r[8])) if r[8] else None,
                    confidence=Decimal(str(r[9])) if r[9] else None,
                )
                for r in interactions
            ]

            total_launched = sum(c[2] or 0 for c in cycles)
            total_paused = sum(c[3] or 0 for c in cycles)

            # Reuse WeeklyReport model — works for any time range
            report = WeeklyReport(
                campaign_id=UUID(campaign_id),
                campaign_name=campaign_name,
                week_start=report_day,
                week_end=report_day,
                total_spend=total_spend,
                total_impressions=total_impressions,
                total_clicks=total_clicks,
                total_conversions=total_conversions,
                avg_ctr=avg_ctr,
                avg_cpa=avg_cpa,
                total_reach=total_reach,
                total_video_views_3s=total_video_views_3s,
                total_video_views_15s=total_video_views_15s,
                total_thruplays=total_thruplays,
                total_link_clicks=total_link_clicks,
                total_landing_page_views=total_landing_page_views,
                total_add_to_carts=total_add_to_carts,
                total_purchases=total_purchases,
                total_purchase_value=total_purchase_value,
                avg_hook_rate=avg_hook_rate,
                avg_hold_rate=avg_hold_rate,
                avg_cpm=avg_cpm,
                avg_frequency=avg_frequency,
                avg_roas=avg_roas,
                avg_cost_per_purchase=avg_cost_per_purchase,
                funnel_stages=funnel_stages,
                best_variant=best_variant,
                worst_variant=worst_variant,
                all_variants=all_variants,
                top_elements=top_elements,
                top_interactions=top_interactions,
                cycles_run=len(cycles),
                variants_launched=total_launched,
                variants_retired=0,
                summary_text=f"Daily optimization summary for {campaign_name}",
            )

        # Print to console
        click.echo(f"\n{'='*60}")
        click.echo(f"DAILY REPORT — {campaign_name}")
        click.echo(f"{'='*60}")
        click.echo(f"Period: {report_day.isoformat()} (yesterday)")
        click.echo(f"Cycles completed: {len(cycles)}")
        click.echo(f"Variants launched: {total_launched}")
        click.echo(f"Variants paused: {total_paused}")
        click.echo(f"\nFull-Funnel Metrics:")
        click.echo(f"  Impressions: {total_impressions:,}")
        click.echo(f"  Reach: {total_reach:,}")
        click.echo(f"  Video Views (3s): {total_video_views_3s:,}  Hook Rate: {avg_hook_rate:.1%}")
        click.echo(f"  Video Views (15s): {total_video_views_15s:,}  Hold Rate: {avg_hold_rate:.1%}")
        click.echo(f"  Link Clicks: {total_link_clicks:,}  CTR: {avg_ctr:.2%}")
        click.echo(f"  Landing Page Views: {total_landing_page_views:,}")
        click.echo(f"  Add to Carts: {total_add_to_carts:,}")
        click.echo(f"  Purchases: {total_purchases:,}")
        click.echo(f"  Revenue: ${total_purchase_value:,.2f}")
        click.echo(f"\nEfficiency:")
        click.echo(f"  Spend: ${total_spend:,.2f}")
        click.echo(f"  CPM: ${avg_cpm:,.2f}")
        click.echo(f"  CPA: {'${:,.2f}'.format(avg_cpa) if avg_cpa else 'N/A'}")
        click.echo(f"  Cost/Purchase: {'${:,.2f}'.format(avg_cost_per_purchase) if avg_cost_per_purchase else 'N/A'}")
        click.echo(f"  ROAS: {'{:.2f}x'.format(avg_roas) if avg_roas else 'N/A'}")
        click.echo(f"  Frequency: {avg_frequency:.1f}")

        if best_variant:
            roas_str = f"ROAS {best_variant.roas:.2f}x" if best_variant.roas else f"CTR {best_variant.ctr:.2%}"
            click.echo(f"\nBest: {best_variant.variant_code} — {roas_str}")
        if worst_variant:
            roas_str = f"ROAS {worst_variant.roas:.2f}x" if worst_variant.roas else f"CTR {worst_variant.ctr:.2%}"
            click.echo(f"Worst: {worst_variant.variant_code} — {roas_str}")

        if top_elements:
            click.echo(f"\nTop Elements:")
            for el in top_elements[:10]:
                roas_str = f" ROAS {el.avg_roas:.2f}x" if el.avg_roas else ""
                click.echo(f"  {el.slot_name}: {el.slot_value} — CTR {el.avg_ctr:.2%}{roas_str} ({el.variants_tested} variants)")

        # Send email if requested
        if send_email:
            if not settings.sendgrid_api_key or settings.sendgrid_api_key.startswith("placeholder"):
                click.echo("\nError: SENDGRID_API_KEY not configured in .env")
            else:
                from src.reports.email import EmailReporter

                reporter = EmailReporter(
                    api_key=settings.sendgrid_api_key,
                    from_email=settings.report_email_from,
                    to_email=settings.report_email_to,
                )
                success = await reporter.send_weekly_report(report, report_type="Daily")
                if success:
                    click.echo(f"\nEmail report sent to {settings.report_email_to}")
                else:
                    click.echo("\nFailed to send email report. Check logs.")

        # Generate static HTML report
        from src.reports.web import render_daily_report as render_daily_html, render_index

        html_path = render_daily_html(report, campaign_name, report_day)
        click.echo(f"\nWeb report: {html_path}")

        # Update index with all existing reports
        from pathlib import Path as _Path

        public_dir = _Path(settings.report_output_dir)
        daily_dates = sorted(
            [p.stem for p in (public_dir / "daily").glob("*.html")],
            reverse=True,
        )
        weekly_labels = sorted(
            [p.stem for p in (public_dir / "weekly").glob("*.html")] if (public_dir / "weekly").exists() else [],
            reverse=True,
        )
        render_index(daily_dates, weekly_labels)

        await close_db()

    asyncio.run(_run())


@cli.command()
@click.option("--campaign-id", required=True, type=str, help="Campaign UUID.")
def backfill_elements(campaign_id: str) -> None:
    """Backfill element performance from existing metrics data."""

    async def _run() -> None:
        from collections import defaultdict

        from sqlalchemy import text as sa_text

        from src.db.engine import close_db, get_session, init_db
        from src.db.queries import upsert_element_interaction, upsert_element_performance
        from src.services.interactions import compute_interactions
        from src.services.stats import element_significance

        await init_db()

        async with get_session() as session:
            # Fetch all non-retired variants with their latest metrics
            rows = await session.execute(
                sa_text("""
                    SELECT v.id, v.genome,
                           COALESCE(m.impressions, 0), COALESCE(m.clicks, 0),
                           COALESCE(m.conversions, 0)
                    FROM variants v
                    LEFT JOIN LATERAL (
                        SELECT impressions, clicks, conversions
                        FROM metrics WHERE variant_id = v.id
                        ORDER BY recorded_at DESC LIMIT 1
                    ) m ON TRUE
                    WHERE v.campaign_id = :id AND v.status != 'retired'
                """),
                {"id": campaign_id},
            )
            variant_rows = rows.fetchall()

            if not variant_rows:
                click.echo("No variants found.")
                await close_db()
                return

            # Compute element performance
            element_ctrs: dict[tuple[str, str], list[tuple[float, int, int]]] = defaultdict(list)
            all_ctrs: list[float] = []

            for row in variant_rows:
                genome = row[1]
                impressions = int(row[2])
                clicks = int(row[3])
                conversions = int(row[4])
                if impressions == 0 or not isinstance(genome, dict):
                    continue
                ctr = clicks / impressions
                all_ctrs.append(ctr)
                for slot_name, slot_value in genome.items():
                    element_ctrs[(slot_name, slot_value)].append((ctr, impressions, conversions))

            global_mean_ctr = sum(all_ctrs) / len(all_ctrs) if all_ctrs else 0.0
            cid = UUID(campaign_id)

            for (slot_name, slot_value), entries in element_ctrs.items():
                ctrs = [c for c, _, _ in entries]
                total_imps = sum(i for _, i, _ in entries)
                total_conv = sum(c for _, _, c in entries)
                weighted_avg = sum(c * i for c, i, _ in entries) / total_imps if total_imps > 0 else 0.0
                _, _, confidence = element_significance(element_ctrs=ctrs, global_mean_ctr=global_mean_ctr)

                await upsert_element_performance(
                    session,
                    campaign_id=cid,
                    slot_name=slot_name,
                    slot_value=slot_value,
                    stats={
                        "variants_tested": len(entries),
                        "avg_ctr": round(weighted_avg, 6),
                        "best_ctr": round(max(ctrs), 6),
                        "worst_ctr": round(min(ctrs), 6),
                        "total_impressions": total_imps,
                        "total_conversions": total_conv,
                        "confidence": round(confidence, 2),
                    },
                )

            click.echo(f"Backfilled {len(element_ctrs)} element performance records.")

            # Compute and persist interactions
            variants_with_metrics = []
            for row in variant_rows:
                genome = row[1]
                impressions = int(row[2])
                clicks = int(row[3])
                if impressions > 0 and isinstance(genome, dict):
                    variants_with_metrics.append((genome, clicks / impressions))

            interactions = compute_interactions(variants_with_metrics, min_combined_variants=2)
            for ix in interactions[:50]:
                await upsert_element_interaction(
                    session,
                    campaign_id=cid,
                    slot_a_name=ix.slot_a_name,
                    slot_a_value=ix.slot_a_value,
                    slot_b_name=ix.slot_b_name,
                    slot_b_value=ix.slot_b_value,
                    stats={
                        "variants_tested": ix.variants_combined,
                        "combined_avg_ctr": round(ix.combined_avg_ctr, 6),
                        "solo_a_avg_ctr": round(ix.solo_a_avg_ctr, 6),
                        "solo_b_avg_ctr": round(ix.solo_b_avg_ctr, 6),
                        "interaction_lift": round(ix.lift, 6),
                    },
                )

            click.echo(f"Backfilled {min(len(interactions), 50)} interaction records.")

        await close_db()

    asyncio.run(_run())


@cli.command()
@click.option("--campaign-id", required=True, type=str, help="Local campaign UUID.")
@click.option("--date-preset", default="last_30d", help="Meta date preset (last_7d, last_30d, etc.).")
@click.option("--ad-account-id", default=None, type=str, help="Override Meta ad account ID (e.g. act_123456).")
@click.option("--dry-run", is_flag=True, default=False, help="Preview what would be imported without writing.")
@click.option("--refresh-metrics", is_flag=True, default=False, help="Re-fetch and update metrics for already-imported ads.")
def import_meta_ads(campaign_id: str, date_preset: str, ad_account_id: str | None, dry_run: bool, refresh_metrics: bool) -> None:
    """Import existing Meta ads and their historical metrics into the system.

    Discovers all ads in the Meta campaign linked to CAMPAIGN_ID,
    creates variant records, and backfills daily metrics snapshots.
    """

    async def _run() -> None:
        import json
        import uuid
        from datetime import datetime, timezone

        from sqlalchemy import text as sa_text

        from src.adapters.meta import MetaAdapter
        from src.db.engine import close_db, get_session, init_db

        settings = get_settings()
        await init_db()

        # 1. Look up local campaign and its platform campaign ID
        async with get_session() as session:
            row = await session.execute(
                sa_text("""
                    SELECT platform, platform_campaign_id, daily_budget
                    FROM campaigns WHERE id = :id
                """),
                {"id": campaign_id},
            )
            campaign = row.fetchone()
            if not campaign:
                click.echo(f"Error: Campaign {campaign_id} not found.")
                await close_db()
                return

            platform = str(campaign[0])
            platform_campaign_id = campaign[1]
            daily_budget = float(campaign[2])

            if platform != "meta":
                click.echo(f"Error: Campaign platform is '{platform}', not 'meta'.")
                await close_db()
                return

            if not platform_campaign_id:
                click.echo("Error: Campaign has no platform_campaign_id set. "
                           "Update it with the Meta campaign ID first.")
                await close_db()
                return

            # 2. Connect to Meta
            if not settings.meta_access_token or settings.meta_access_token.startswith("placeholder"):
                click.echo("Error: Meta API credentials not configured in .env")
                await close_db()
                return

            effective_ad_account = ad_account_id or settings.meta_ad_account_id
            adapter = MetaAdapter(
                app_id=settings.meta_app_id,
                app_secret=settings.meta_app_secret,
                access_token=settings.meta_access_token,
                ad_account_id=effective_ad_account,
                page_id=settings.meta_page_id,
                landing_page_url=settings.meta_landing_page_url,
            )

            # 3. List all ads in the campaign
            click.echo(f"\nDiscovering ads in Meta campaign {platform_campaign_id}...")
            ads = await adapter.list_campaign_ads(platform_campaign_id)

            if not ads:
                click.echo("No ads found in Meta campaign.")
                await close_db()
                return

            click.echo(f"Found {len(ads)} ads:\n")
            for ad in ads:
                click.echo(f"  [{ad['status']}] {ad['ad_id']} — {ad['ad_name']}")
                click.echo(f"    Headline: {ad['headline']}")
                click.echo(f"    Body: {str(ad['body'])[:80]}")
                click.echo()

            if dry_run:
                click.echo("Dry run — no data written.")
                await close_db()
                return

            # 4. Check which ads are already imported (by platform_ad_id)
            existing_row = await session.execute(
                sa_text("""
                    SELECT platform_ad_id FROM deployments d
                    JOIN variants v ON v.id = d.variant_id
                    WHERE v.campaign_id = :id
                """),
                {"id": campaign_id},
            )
            existing_ad_ids = {str(r[0]) for r in existing_row.fetchall()}

            imported = 0
            metrics_imported = 0

            for ad in ads:
                ad_id = str(ad["ad_id"])

                if ad_id in existing_ad_ids and not refresh_metrics:
                    click.echo(f"  Skipping {ad_id} (already imported, use --refresh-metrics to update)")
                    continue

                if ad_id in existing_ad_ids and refresh_metrics:
                    # Just refresh metrics for this existing ad
                    click.echo(f"  Refreshing metrics for {ad_id}...")
                    dep_row = await session.execute(
                        sa_text("""
                            SELECT d.id, d.variant_id FROM deployments d
                            JOIN variants v ON v.id = d.variant_id
                            WHERE d.platform_ad_id = :ad_id AND v.campaign_id = :cid
                        """),
                        {"ad_id": ad_id, "cid": UUID(campaign_id)},
                    )
                    dep = dep_row.fetchone()
                    if dep:
                        deployment_id = dep[0]
                        variant_id = dep[1]
                        try:
                            daily_metrics = await adapter.get_historical_metrics(
                                ad_id, date_preset=date_preset,
                            )
                            for day in daily_metrics:
                                if int(day["impressions"]) == 0:
                                    continue
                                day_ts = datetime.strptime(
                                    str(day["date_start"]), "%Y-%m-%d"
                                ).replace(hour=23, minute=59, tzinfo=timezone.utc)

                                await session.execute(
                                    sa_text("""
                                        INSERT INTO metrics (variant_id, deployment_id,
                                                            impressions, clicks, conversions, spend,
                                                            reach, video_views_3s, video_views_15s,
                                                            thruplays, link_clicks, landing_page_views,
                                                            add_to_carts, purchases, purchase_value,
                                                            recorded_at)
                                        VALUES (:vid, :did,
                                                :impressions, :clicks, :conversions, :spend,
                                                :reach, :video_views_3s, :video_views_15s,
                                                :thruplays, :link_clicks, :landing_page_views,
                                                :add_to_carts, :purchases, :purchase_value,
                                                :recorded_at)
                                        ON CONFLICT (recorded_at, variant_id) DO UPDATE SET
                                            impressions = EXCLUDED.impressions,
                                            clicks = EXCLUDED.clicks,
                                            conversions = EXCLUDED.conversions,
                                            spend = EXCLUDED.spend,
                                            reach = EXCLUDED.reach,
                                            video_views_3s = EXCLUDED.video_views_3s,
                                            video_views_15s = EXCLUDED.video_views_15s,
                                            thruplays = EXCLUDED.thruplays,
                                            link_clicks = EXCLUDED.link_clicks,
                                            landing_page_views = EXCLUDED.landing_page_views,
                                            add_to_carts = EXCLUDED.add_to_carts,
                                            purchases = EXCLUDED.purchases,
                                            purchase_value = EXCLUDED.purchase_value
                                    """),
                                    {
                                        "vid": variant_id,
                                        "did": deployment_id,
                                        "impressions": int(day["impressions"]),
                                        "clicks": int(day["clicks"]),
                                        "conversions": int(day["conversions"]),
                                        "spend": Decimal(str(day["spend"])),
                                        "reach": int(day.get("reach", 0)),
                                        "video_views_3s": int(day.get("video_views_3s", 0)),
                                        "video_views_15s": int(day.get("video_views_15s", 0)),
                                        "thruplays": int(day.get("thruplays", 0)),
                                        "link_clicks": int(day.get("link_clicks", 0)),
                                        "landing_page_views": int(day.get("landing_page_views", 0)),
                                        "add_to_carts": int(day.get("add_to_carts", 0)),
                                        "purchases": int(day.get("purchases", 0)),
                                        "purchase_value": Decimal(str(day.get("purchase_value", 0))),
                                        "recorded_at": day_ts,
                                    },
                                )
                                metrics_imported += 1
                            if daily_metrics:
                                click.echo(f"    → Updated {len(daily_metrics)} days of metrics")
                        except Exception as exc:
                            click.echo(f"    → Warning: Could not fetch metrics: {exc}")
                    await session.flush()
                    continue

                # 5. Build a best-effort genome from the creative data
                genome: dict[str, str] = {
                    "headline": str(ad.get("headline", "")),
                    "subhead": str(ad.get("body", "")),
                    "cta_text": _meta_cta_to_genome(str(ad.get("cta_type", ""))),
                    "cta_color": "blue",  # default — not available from Meta
                    "hero_style": "lifestyle_photo",  # default
                    "social_proof": "none",
                    "urgency": "none",
                    "audience": "broad",
                }

                # Get next variant code
                code_row = await session.execute(
                    sa_text("SELECT next_variant_code(:id)"),
                    {"id": UUID(campaign_id)},
                )
                variant_code = str(code_row.scalar_one())

                # Map Meta status to our status
                meta_status = str(ad["status"])
                status = "active" if meta_status == "ACTIVE" else "paused"

                # Insert variant
                variant_id = uuid.uuid4()
                await session.execute(
                    sa_text("""
                        INSERT INTO variants (id, campaign_id, variant_code, genome, status,
                                             generation, hypothesis, created_at)
                        VALUES (:id, :cid, :code, :genome, :status,
                                0, :hypothesis, NOW())
                    """),
                    {
                        "id": variant_id,
                        "cid": UUID(campaign_id),
                        "code": variant_code,
                        "genome": json.dumps(genome),
                        "status": status,
                        "hypothesis": f"Imported from Meta ad {ad_id}",
                    },
                )

                # Insert deployment
                deployment_id = uuid.uuid4()
                per_variant_budget = daily_budget / max(len(ads), 1)
                await session.execute(
                    sa_text("""
                        INSERT INTO deployments (id, variant_id, platform, platform_ad_id,
                                                daily_budget, is_active, created_at, updated_at)
                        VALUES (:id, :vid, 'meta', :ad_id,
                                :budget, :active, NOW(), NOW())
                    """),
                    {
                        "id": deployment_id,
                        "vid": variant_id,
                        "ad_id": ad_id,
                        "budget": Decimal(str(round(per_variant_budget, 2))),
                        "active": status == "active",
                    },
                )

                click.echo(f"  Imported {ad_id} → {variant_code} ({status})")
                imported += 1

                # 6. Fetch historical metrics
                try:
                    daily_metrics = await adapter.get_historical_metrics(
                        ad_id, date_preset=date_preset,
                    )
                    for day in daily_metrics:
                        if int(day["impressions"]) == 0:
                            continue
                        # Parse the date into a timestamp
                        day_ts = datetime.strptime(
                            str(day["date_start"]), "%Y-%m-%d"
                        ).replace(hour=23, minute=59, tzinfo=timezone.utc)

                        await session.execute(
                            sa_text("""
                                INSERT INTO metrics (variant_id, deployment_id,
                                                    impressions, clicks, conversions, spend,
                                                    reach, video_views_3s, video_views_15s,
                                                    thruplays, link_clicks, landing_page_views,
                                                    add_to_carts, purchases, purchase_value,
                                                    recorded_at)
                                VALUES (:vid, :did,
                                        :impressions, :clicks, :conversions, :spend,
                                        :reach, :video_views_3s, :video_views_15s,
                                        :thruplays, :link_clicks, :landing_page_views,
                                        :add_to_carts, :purchases, :purchase_value,
                                        :recorded_at)
                                ON CONFLICT (recorded_at, variant_id) DO UPDATE SET
                                    impressions = EXCLUDED.impressions,
                                    clicks = EXCLUDED.clicks,
                                    conversions = EXCLUDED.conversions,
                                    spend = EXCLUDED.spend,
                                    reach = EXCLUDED.reach,
                                    video_views_3s = EXCLUDED.video_views_3s,
                                    video_views_15s = EXCLUDED.video_views_15s,
                                    thruplays = EXCLUDED.thruplays,
                                    link_clicks = EXCLUDED.link_clicks,
                                    landing_page_views = EXCLUDED.landing_page_views,
                                    add_to_carts = EXCLUDED.add_to_carts,
                                    purchases = EXCLUDED.purchases,
                                    purchase_value = EXCLUDED.purchase_value
                            """),
                            {
                                "vid": variant_id,
                                "did": deployment_id,
                                "impressions": int(day["impressions"]),
                                "clicks": int(day["clicks"]),
                                "conversions": int(day["conversions"]),
                                "spend": Decimal(str(day["spend"])),
                                "reach": int(day.get("reach", 0)),
                                "video_views_3s": int(day.get("video_views_3s", 0)),
                                "video_views_15s": int(day.get("video_views_15s", 0)),
                                "thruplays": int(day.get("thruplays", 0)),
                                "link_clicks": int(day.get("link_clicks", 0)),
                                "landing_page_views": int(day.get("landing_page_views", 0)),
                                "add_to_carts": int(day.get("add_to_carts", 0)),
                                "purchases": int(day.get("purchases", 0)),
                                "purchase_value": Decimal(str(day.get("purchase_value", 0))),
                                "recorded_at": day_ts,
                            },
                        )
                        metrics_imported += 1

                    if daily_metrics:
                        click.echo(f"    → {len(daily_metrics)} days of metrics")
                except Exception as exc:
                    click.echo(f"    → Warning: Could not fetch metrics: {exc}")

            await session.flush()

        click.echo(f"\nImport complete: {imported} ads, {metrics_imported} metric snapshots")
        click.echo("Run 'backfill-elements' to compute element performance from the imported data.")
        await close_db()

    asyncio.run(_run())


def _meta_cta_to_genome(cta_type: str) -> str:
    """Map a Meta CTA type back to a gene pool value."""
    mapping: dict[str, str] = {
        "GET_OFFER": "Claim my discount",
        "SHOP_NOW": "Shop now",
        "LEARN_MORE": "Learn more",
        "SIGN_UP": "Sign up free",
        "SUBSCRIBE": "Sign up free",
        "DOWNLOAD": "Get started",
        "BOOK_TRAVEL": "Get started",
        "CONTACT_US": "Learn more",
    }
    return mapping.get(cta_type, "Learn more")


@cli.command()
@click.option("--campaign-id", required=True, type=str, help="Campaign UUID.")
@click.option(
    "--type",
    "asset_type",
    default="all",
    type=click.Choice(["image", "video", "all"]),
    help="Filter by asset type.",
)
@click.option("--ad-account-id", default=None, type=str, help="Override Meta ad account ID.")
def sync_media_library(campaign_id: str, asset_type: str, ad_account_id: str | None) -> None:
    """Sync images and videos from Meta's media library into the system.

    Fetches all images/videos from the ad account, stores them in the
    media_assets table, and auto-adds active assets to the gene pool.
    """

    async def _run() -> None:
        import uuid as uuid_mod

        from sqlalchemy import text as sa_text

        from src.adapters.meta import MetaAdapter
        from src.db.engine import close_db, get_session, init_db

        settings = get_settings()
        await init_db()

        async with get_session() as session:
            # Verify campaign exists
            row = await session.execute(
                sa_text("SELECT platform FROM campaigns WHERE id = :id"),
                {"id": campaign_id},
            )
            campaign = row.fetchone()
            if not campaign:
                click.echo(f"Error: Campaign {campaign_id} not found.")
                await close_db()
                return

            if str(campaign[0]) != "meta":
                click.echo(f"Error: Campaign platform is '{campaign[0]}', not 'meta'.")
                await close_db()
                return

            # Connect to Meta
            if not settings.meta_access_token or settings.meta_access_token.startswith("placeholder"):
                click.echo("Error: Meta API credentials not configured.")
                await close_db()
                return

            effective_account = ad_account_id or settings.meta_ad_account_id
            adapter = MetaAdapter(
                app_id=settings.meta_app_id,
                app_secret=settings.meta_app_secret,
                access_token=settings.meta_access_token,
                ad_account_id=effective_account,
                page_id=settings.meta_page_id,
                landing_page_url=settings.meta_landing_page_url,
            )

            click.echo(f"\nFetching {asset_type} assets from Meta account {effective_account}...")
            assets = await adapter.list_media_library(asset_type=asset_type)

            if not assets:
                click.echo("No media assets found.")
                await close_db()
                return

            click.echo(f"Found {len(assets)} assets:\n")
            synced = 0
            for i, asset in enumerate(assets, 1):
                size_info = f"{asset.width}x{asset.height}" if asset.width else ""
                dur_info = f" ({asset.duration_secs:.0f}s)" if asset.duration_secs else ""
                click.echo(f"  [{i}] [{asset.asset_type.upper()}] {asset.name} {size_info}{dur_info}")
                click.echo(f"      ID: {asset.platform_id}")
                if asset.thumbnail_url:
                    click.echo(f"      Thumb: {asset.thumbnail_url[:80]}")

                # Upsert into media_assets
                await session.execute(
                    sa_text("""
                        INSERT INTO media_assets (
                            id, campaign_id, asset_type, platform, platform_id,
                            name, thumbnail_url, source_url, width, height,
                            duration_secs, metadata, is_active
                        ) VALUES (
                            :id, :cid, :atype, 'meta', :pid,
                            :name, :thumb, :source, :width, :height,
                            :duration, :meta, TRUE
                        )
                        ON CONFLICT (campaign_id, platform, platform_id) DO UPDATE SET
                            name = EXCLUDED.name,
                            thumbnail_url = EXCLUDED.thumbnail_url,
                            source_url = EXCLUDED.source_url,
                            width = EXCLUDED.width,
                            height = EXCLUDED.height,
                            duration_secs = EXCLUDED.duration_secs,
                            metadata = EXCLUDED.metadata
                    """),
                    {
                        "id": uuid_mod.uuid4(),
                        "cid": UUID(campaign_id),
                        "atype": asset.asset_type,
                        "pid": asset.platform_id,
                        "name": asset.name,
                        "thumb": asset.thumbnail_url,
                        "source": asset.source_url,
                        "width": asset.width or None,
                        "height": asset.height or None,
                        "duration": asset.duration_secs or None,
                        "meta": json.dumps(asset.metadata, default=str),  # JSONB
                    },
                )
                synced += 1

                # Auto-add to gene pool as media_asset slot
                gene_pool_value = asset.name or f"{asset.asset_type}_{asset.platform_id[:12]}"
                gene_pool_desc = f"{asset.asset_type.title()}: {asset.name}"
                if asset.duration_secs:
                    gene_pool_desc += f" ({asset.duration_secs:.0f}s)"

                await session.execute(
                    sa_text("""
                        INSERT INTO gene_pool (id, slot_name, slot_value, description, is_active)
                        VALUES (:id, 'media_asset', :value, :desc, TRUE)
                        ON CONFLICT (slot_name, slot_value) DO UPDATE SET
                            description = EXCLUDED.description,
                            is_active = TRUE
                    """),
                    {
                        "id": uuid_mod.uuid4(),
                        "value": gene_pool_value,
                        "desc": gene_pool_desc,
                    },
                )

            await session.flush()
            click.echo(f"\nSynced {synced} assets. Gene pool updated with media_asset entries.")
            click.echo("Run a cycle to start testing with real media.")

        await close_db()

    asyncio.run(_run())


@cli.command()
@click.option("--campaign-id", required=True, type=str, help="Campaign UUID.")
def list_media(campaign_id: str) -> None:
    """List synced media assets for a campaign."""

    async def _run() -> None:
        from sqlalchemy import text as sa_text

        from src.db.engine import close_db, get_session, init_db

        await init_db()

        async with get_session() as session:
            row = await session.execute(
                sa_text("""
                    SELECT asset_type, platform_id, name, thumbnail_url,
                           width, height, duration_secs, is_active
                    FROM media_assets
                    WHERE campaign_id = :id
                    ORDER BY asset_type, name
                """),
                {"id": campaign_id},
            )
            assets = row.fetchall()

            if not assets:
                click.echo(f"No media assets found for campaign {campaign_id}.")
                click.echo("Run 'sync-media-library' to import from Meta.")
                await close_db()
                return

            click.echo(f"\nMedia assets for campaign {campaign_id}:\n")
            for i, a in enumerate(assets, 1):
                status = "ACTIVE" if a[7] else "INACTIVE"
                size = f" {a[4]}x{a[5]}" if a[4] else ""
                dur = f" ({a[6]:.0f}s)" if a[6] else ""
                click.echo(f"  [{i}] [{a[0].upper()}] [{status}] {a[2]}{size}{dur}")
                click.echo(f"      Platform ID: {a[1]}")

            click.echo(f"\n{len(assets)} total assets")

        await close_db()

    asyncio.run(_run())


def main() -> None:
    """Package entry point."""
    cli()


if __name__ == "__main__":
    main()
