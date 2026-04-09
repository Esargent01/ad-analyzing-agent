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
@click.option(
    "--generate",
    "with_generate",
    is_flag=True,
    default=False,
    help="Also generate new variants in this cycle (off by default — generation happens in the weekly flow).",
)
@click.option(
    "--no-generate",
    "legacy_no_generate",
    is_flag=True,
    default=False,
    hidden=True,
    help="Deprecated: monitoring-only is now the default. Retained for backward compatibility.",
)
def run_cycle(campaign_id: str, with_generate: bool, legacy_no_generate: bool) -> None:
    """Run a single optimization cycle for a campaign.

    By default this is monitoring-only: metrics are polled, element
    performance is updated, and approved variants are deployed. New
    variant generation happens in the weekly flow (``weekly-report``).

    Pass ``--generate`` to run the legacy full cycle including LLM
    generation.
    """

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
        # Monitoring-only by default; --generate flips it back on.
        # --no-generate is still accepted as a no-op for backward compatibility.
        skip_generate = not with_generate or legacy_no_generate
        report = await orchestrator.run_cycle(UUID(campaign_id), skip_generate=skip_generate)
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
        from src.dashboard.tokens import create_review_token
        from src.db.engine import close_db, get_session, init_db
        from src.services.reports import build_weekly_report, default_last_full_week
        from src.services.weekly import run_weekly_generation

        settings = get_settings()
        await init_db()

        week_start, week_end = default_last_full_week()
        campaign_uuid = UUID(campaign_id)

        async with get_session() as session:
            # Validate the campaign exists before running generation (matches prior behavior).
            from sqlalchemy import text as sa_text

            campaign_row = await session.execute(
                sa_text("SELECT name FROM campaigns WHERE id = :id"),
                {"id": campaign_id},
            )
            if not campaign_row.fetchone():
                click.echo(f"Error: Campaign {campaign_id} not found.")
                await close_db()
                return

            # Weekly generation pass: expire stale proposals, generate new ones
            click.echo("Running weekly generation pass...")
            try:
                expired_count, generation_paused = await run_weekly_generation(
                    session, campaign_uuid
                )
                if expired_count:
                    click.echo(
                        f"  Expired {expired_count} stale proposal(s) (>14 days old)"
                    )
                if generation_paused:
                    click.echo(
                        "  Generation paused — approval queue at capacity"
                    )
            except Exception as exc:  # noqa: BLE001 — surface but don't abort report
                click.echo(f"  Warning: generation pass failed: {exc}")
                expired_count = 0
                generation_paused = False

            # Pre-compute review URL only if there will be proposals to review.
            # The service loads proposals itself; peek at the count via a light query.
            pending_row = await session.execute(
                sa_text(
                    "SELECT COUNT(*) FROM approval_queue "
                    "WHERE campaign_id = :id AND approved IS NULL AND reviewed_at IS NULL"
                ),
                {"id": campaign_id},
            )
            pending_count = int(pending_row.scalar_one() or 0)
            review_url = (
                f"{settings.report_base_url.rstrip('/')}/review/{create_review_token(campaign_uuid)}"
                if pending_count > 0
                else None
            )

            report = await build_weekly_report(
                session,
                campaign_uuid,
                week_start,
                week_end=week_end,
                expired_count=expired_count,
                generation_paused=generation_paused,
                review_url=review_url,
            )

        campaign_name = report.campaign_name
        click.echo(f"  {len(report.proposed_variants)} proposal(s) pending review")

        if report.cycles_run == 0:
            click.echo(
                f"No monitoring cycles found for week {week_start} to {week_end}. "
                f"Report will still include proposed variants."
            )

        # Print to console
        click.echo(f"\n{'='*60}")
        click.echo(f"WEEKLY REPORT — {campaign_name}")
        click.echo(f"{'='*60}")
        click.echo(f"Period: {report.week_start} to {report.week_end}")
        click.echo(f"Cycles completed: {report.cycles_run}")
        click.echo(f"Variants launched: {report.variants_launched}")
        click.echo(f"\nFull-Funnel Metrics:")
        click.echo(f"  Impressions: {report.total_impressions:,}")
        click.echo(f"  Reach: {report.total_reach:,}")
        click.echo(f"  Video Views (3s): {report.total_video_views_3s:,}  Hook Rate: {report.avg_hook_rate:.1%}")
        click.echo(f"  Video Views (15s): {report.total_video_views_15s:,}  Hold Rate: {report.avg_hold_rate:.1%}")
        click.echo(f"  Link Clicks: {report.total_link_clicks:,}  CTR: {report.avg_ctr:.2%}")
        click.echo(f"  Landing Page Views: {report.total_landing_page_views:,}")
        click.echo(f"  Add to Carts: {report.total_add_to_carts:,}")
        click.echo(f"  Purchases: {report.total_purchases:,}")
        click.echo(f"  Revenue: ${report.total_purchase_value:,.2f}")
        click.echo(f"\nEfficiency:")
        click.echo(f"  Spend: ${report.total_spend:,.2f}")
        click.echo(f"  CPM: ${report.avg_cpm:,.2f}")
        click.echo(f"  CPA: {'${:,.2f}'.format(report.avg_cpa) if report.avg_cpa else 'N/A'}")
        click.echo(f"  Cost/Purchase: {'${:,.2f}'.format(report.avg_cost_per_purchase) if report.avg_cost_per_purchase else 'N/A'}")
        click.echo(f"  ROAS: {'{:.2f}x'.format(report.avg_roas) if report.avg_roas else 'N/A'}")
        click.echo(f"  Frequency: {report.avg_frequency:.1f}")

        best_variant = report.best_variant
        worst_variant = report.worst_variant
        if best_variant:
            roas_str = f"ROAS {best_variant.roas:.2f}x" if best_variant.roas else f"CTR {best_variant.ctr:.2%}"
            click.echo(f"\nBest: {best_variant.variant_code} — {roas_str}")
        if worst_variant:
            roas_str = f"ROAS {worst_variant.roas:.2f}x" if worst_variant.roas else f"CTR {worst_variant.ctr:.2%}"
            click.echo(f"Worst: {worst_variant.variant_code} — {roas_str}")

        if report.top_elements:
            click.echo(f"\nTop Elements:")
            for el in report.top_elements[:10]:
                roas_str = f" ROAS {el.avg_roas:.2f}x" if el.avg_roas else ""
                click.echo(f"  {el.slot_name}: {el.slot_value} — CTR {el.avg_ctr:.2%}{roas_str} ({el.variants_tested} variants)")

        if report.proposed_variants:
            click.echo(f"\nNext week's experiments ({len(report.proposed_variants)} proposed):")
            for pv in report.proposed_variants:
                badge = f" [expires in {pv.days_until_expiry}d]" if pv.classification == "expiring_soon" else ""
                click.echo(f"  {pv.variant_code}: {pv.genome_summary}{badge}")
                if pv.hypothesis:
                    click.echo(f"    Hypothesis: {pv.hypothesis}")
            if report.review_url:
                click.echo(f"\n  Review link: {report.review_url}")

        week_label = f"{week_start.isocalendar()[0]}-W{week_start.isocalendar()[1]:02d}"

        # Send email if requested (v2 redesigned template)
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
                success = await reporter.send_weekly_report_v2(
                    report,
                    campaign_name=campaign_name,
                    week_label=week_label,
                    base_url=settings.report_base_url,
                    review_url=report.review_url,
                )
                if success:
                    click.echo(f"\nEmail report sent to {settings.report_email_to}")
                else:
                    click.echo("\nFailed to send email report. Check logs.")

        # Send via Slack if configured
        if settings.slack_webhook_url and not settings.slack_webhook_url.startswith("https://hooks.slack.com/services/PLACEHOLDER"):
            from src.reports.slack import SlackReporter

            slack = SlackReporter(webhook_url=settings.slack_webhook_url)
            summary = (
                f"Weekly: {report.cycles_run} cycles, "
                f"{report.variants_launched} launched, "
                f"{len(report.proposed_variants)} pending review"
            )
            await slack.send_cycle_report(
                campaign_name=campaign_name,
                cycle_number=0,
                summary=summary,
                actions=[],
            )
            click.echo("\nSlack report sent.")

        # Generate static HTML report
        from src.reports.web import render_weekly_report as render_weekly_html, render_index

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
        from datetime import date, timedelta

        from src.db.engine import close_db, get_session, init_db
        from src.services.reports import build_daily_report

        settings = get_settings()
        await init_db()

        # Report on a single calendar day — yesterday by default
        if report_date:
            report_day = date.fromisoformat(report_date)
        else:
            report_day = date.today() - timedelta(days=1)

        campaign_uuid = UUID(campaign_id)

        v2_report = None
        async with get_session() as session:
            try:
                v2_report = await build_daily_report(
                    session, campaign_uuid, report_day
                )
            except LookupError:
                click.echo(f"Error: Campaign {campaign_id} not found.")
                await close_db()
                return

        campaign_name = v2_report.campaign_name

        # Print to console
        click.echo(f"\n{'='*60}")
        click.echo(f"DAILY REPORT — {campaign_name}")
        click.echo(f"{'='*60}")
        click.echo(f"Period: {report_day.isoformat()} (yesterday)")
        click.echo(f"Cycles completed: {v2_report.cycle_number}")

        total_impressions = sum(v.impressions for v in v2_report.variants)
        total_clicks = sum(v.link_clicks for v in v2_report.variants)
        total_reach = sum(v.reach for v in v2_report.variants)
        total_video_views_3s = sum(v.video_views_3s for v in v2_report.variants)
        total_video_views_15s = sum(v.video_views_15s for v in v2_report.variants)
        total_add_to_carts = sum(v.add_to_carts for v in v2_report.variants)
        total_landing_page_views = sum(v.landing_page_views for v in v2_report.variants)
        total_purchase_value = sum((v.purchase_value for v in v2_report.variants), Decimal("0"))

        avg_hook_rate_f = v2_report.avg_hook_rate_pct / 100
        avg_hold_rate_f = (
            total_video_views_15s / total_video_views_3s
            if total_video_views_3s > 0
            else 0.0
        )
        avg_ctr_f = (
            total_clicks / total_impressions if total_impressions > 0 else 0.0
        )
        avg_cpm_f = (
            float(v2_report.total_spend) / total_impressions * 1000
            if total_impressions > 0
            else 0.0
        )
        avg_frequency_f = (
            total_impressions / total_reach if total_reach > 0 else 0.0
        )

        click.echo(f"\nFull-Funnel Metrics:")
        click.echo(f"  Impressions: {total_impressions:,}")
        click.echo(f"  Reach: {total_reach:,}")
        click.echo(f"  Video Views (3s): {total_video_views_3s:,}  Hook Rate: {avg_hook_rate_f:.1%}")
        click.echo(f"  Video Views (15s): {total_video_views_15s:,}  Hold Rate: {avg_hold_rate_f:.1%}")
        click.echo(f"  Link Clicks: {total_clicks:,}  CTR: {avg_ctr_f:.2%}")
        click.echo(f"  Landing Page Views: {total_landing_page_views:,}")
        click.echo(f"  Add to Carts: {total_add_to_carts:,}")
        click.echo(f"  Purchases: {v2_report.total_purchases:,}")
        click.echo(f"  Revenue: ${total_purchase_value:,.2f}")
        click.echo(f"\nEfficiency:")
        click.echo(f"  Spend: ${v2_report.total_spend:,.2f}")
        click.echo(f"  CPM: ${avg_cpm_f:,.2f}")
        cpa_str = (
            f"${v2_report.avg_cost_per_purchase:,.2f}"
            if v2_report.avg_cost_per_purchase
            else "N/A"
        )
        click.echo(f"  Cost/Purchase: {cpa_str}")
        click.echo(
            f"  ROAS: {'{:.2f}x'.format(v2_report.avg_roas) if v2_report.avg_roas else 'N/A'}"
        )
        click.echo(f"  Frequency: {avg_frequency_f:.1f}")

        if v2_report.best_variant:
            bv = v2_report.best_variant
            cpa_fmt = f"${bv.cost_per_purchase:,.2f}" if bv.cost_per_purchase else "N/A"
            click.echo(f"\nBest: {bv.variant_code} — CPA {cpa_fmt}")

        # Render v2 HTML report
        from src.reports.web import render_daily_report_v2, render_index

        try:
            v2_path = render_daily_report_v2(v2_report)
            click.echo(f"\nWeb report: {v2_path}")
        except Exception as exc:
            import traceback
            click.echo(f"\nWarning: v2 report generation failed: {exc}")
            traceback.print_exc()

        # Send v2 daily email if requested
        if send_email:
            if not settings.sendgrid_api_key or settings.sendgrid_api_key.startswith("placeholder"):
                click.echo("\nError: SENDGRID_API_KEY not configured in .env")
            elif v2_report is not None:
                from src.reports.email import EmailReporter

                reporter = EmailReporter(
                    api_key=settings.sendgrid_api_key,
                    from_email=settings.report_email_from,
                    to_email=settings.report_email_to,
                )
                success = await reporter.send_daily_report(
                    v2_report, base_url=settings.report_base_url,
                )
                if success:
                    click.echo(f"\nEmail report sent to {settings.report_email_to}")
                else:
                    click.echo("\nFailed to send email report. Check logs.")
            else:
                click.echo("\nWarning: v2 report not available, email not sent.")

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
                    "media_asset": str(ad.get("media_asset", "placeholder_lifestyle")),
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


# ---------------------------------------------------------------------------
# Gene pool management
# ---------------------------------------------------------------------------

VALID_SLOTS = [
    "headline", "subhead", "cta_text", "media_asset", "audience",
]


@cli.group()
def pool() -> None:
    """Manage the gene pool — creative elements available for testing."""


@pool.command("add")
@click.option("--slot", required=True, type=click.Choice(VALID_SLOTS), help="Slot name.")
@click.option("--value", required=True, type=str, help="Slot value to add.")
@click.option("--description", default=None, type=str, help="Human-readable description.")
@click.option("--meta-audience-id", default=None, type=str, help="Meta custom audience ID (audience slot only).")
def pool_add(slot: str, value: str, description: str | None, meta_audience_id: str | None) -> None:
    """Add a new entry to the gene pool."""

    async def _run() -> None:
        from src.db.engine import get_session, close_db
        from src.db.queries import add_gene_pool_entry

        metadata = None
        if meta_audience_id:
            if slot != "audience":
                click.echo("Error: --meta-audience-id is only valid for the audience slot.")
                return
            metadata = {"meta_audience_id": meta_audience_id}

        async with get_session() as session:
            try:
                entry = await add_gene_pool_entry(
                    session,
                    slot_name=slot,
                    slot_value=value,
                    description=description,
                    metadata=metadata,
                    source="user",
                )
                click.echo(f"Added: [{slot}] {value} (id: {entry.id})")
            except Exception as e:
                if "uq_gene_pool_slot_value" in str(e):
                    click.echo(f"Error: '{value}' already exists in slot '{slot}'.")
                else:
                    click.echo(f"Error: {e}")

        await close_db()

    asyncio.run(_run())


@pool.command("list")
@click.option("--slot", default=None, type=click.Choice(VALID_SLOTS), help="Filter by slot name.")
def pool_list(slot: str | None) -> None:
    """List gene pool entries."""

    async def _run() -> None:
        from src.db.engine import get_session, close_db
        from src.db.queries import list_gene_pool_entries

        async with get_session() as session:
            entries = await list_gene_pool_entries(session, slot_name=slot)

        if not entries:
            click.echo("No gene pool entries found.")
            await close_db()
            return

        current_slot = None
        for entry in entries:
            if entry.slot_name != current_slot:
                current_slot = entry.slot_name
                click.echo(f"\n{current_slot.upper()} ({sum(1 for e in entries if e.slot_name == current_slot)} entries)")
                click.echo("-" * 60)
            source_tag = f" [{entry.source}]" if entry.source and entry.source != "seed" else ""
            meta_tag = ""
            if entry.metadata_ and entry.metadata_.get("meta_audience_id"):
                meta_tag = f" (Meta: {entry.metadata_['meta_audience_id']})"
            desc = f" — {entry.description}" if entry.description else ""
            click.echo(f"  {entry.slot_value}{desc}{source_tag}{meta_tag}")

        await close_db()

    asyncio.run(_run())


@pool.command("retire")
@click.option("--slot", required=True, type=click.Choice(VALID_SLOTS), help="Slot name.")
@click.option("--value", required=True, type=str, help="Slot value to retire.")
def pool_retire(slot: str, value: str) -> None:
    """Retire a gene pool entry (prevents future use, does not affect active variants)."""

    async def _run() -> None:
        from src.db.engine import get_session, close_db
        from src.db.queries import deactivate_gene_pool_entry

        async with get_session() as session:
            success = await deactivate_gene_pool_entry(session, slot_name=slot, slot_value=value)

        if success:
            click.echo(f"Retired: [{slot}] {value}")
        else:
            click.echo(f"Not found: [{slot}] {value}")

        await close_db()

    asyncio.run(_run())


@pool.command("suggest")
@click.option("--slot", default=None, type=click.Choice(["headline", "subhead", "cta_text"]), help="Slot to suggest for (default: all text slots).")
@click.option("--brand-context", default=None, type=str, help="Brand voice / product description for context.")
@click.option("--count", default=5, type=int, help="Number of suggestions to generate.")
@click.option("--campaign-id", default=None, type=str, help="Campaign UUID for performance-informed suggestions.")
def pool_suggest(slot: str | None, brand_context: str | None, count: int, campaign_id: str | None) -> None:
    """Use the LLM to suggest new creative text for the gene pool."""

    async def _run() -> None:
        from src.agents.copywriter import CopywriterAgent
        from src.db.engine import get_session, close_db
        from src.db.queries import add_gene_pool_entry, get_element_rankings, list_gene_pool_entries

        settings = get_settings()
        if not settings.anthropic_api_key or settings.anthropic_api_key.startswith("placeholder"):
            click.echo("Error: ANTHROPIC_API_KEY not configured.")
            return

        async with get_session() as session:
            # Load current gene pool for context
            existing = await list_gene_pool_entries(session, slot_name=slot)

            # Load performance data if campaign specified
            top_elements = None
            if campaign_id:
                top_elements = await get_element_rankings(session, UUID(campaign_id))

            agent = CopywriterAgent(
                api_key=settings.anthropic_api_key,
                model=settings.anthropic_model,
            )

            click.echo(f"Generating {count} suggestions...")
            try:
                suggestions = await agent.suggest_entries(
                    existing_entries=existing,
                    top_elements=top_elements,
                    slot_name=slot,
                    brand_context=brand_context,
                    count=count,
                )
            except Exception as e:
                click.echo(f"Error: {e}")
                await close_db()
                return

            # Insert as pending (inactive) entries
            for s in suggestions:
                await add_gene_pool_entry(
                    session,
                    slot_name=s.slot_name,
                    slot_value=s.value,
                    description=s.description,
                    source="llm_suggested",
                )
                click.echo(f"  [{s.slot_name}] {s.value}")
                click.echo(f"    Rationale: {s.rationale}")

            click.echo(f"\n{len(suggestions)} suggestion(s) saved as pending.")
            click.echo("Run 'adagent pool review' to see them, 'adagent pool approve --all' to activate.")

        await close_db()

    asyncio.run(_run())


@pool.command("review")
def pool_review() -> None:
    """List pending LLM-suggested gene pool entries awaiting approval."""

    async def _run() -> None:
        from src.db.engine import get_session, close_db
        from src.db.queries import get_pending_suggestions

        async with get_session() as session:
            suggestions = await get_pending_suggestions(session)

        if not suggestions:
            click.echo("No pending suggestions.")
            await close_db()
            return

        click.echo(f"\n{len(suggestions)} pending suggestion(s):")
        click.echo("-" * 60)
        for s in suggestions:
            desc = f" — {s.description}" if s.description else ""
            click.echo(f"  [{s.id}] {s.slot_name}: {s.slot_value}{desc}")

        click.echo(f"\nRun 'adagent pool approve --id <UUID>' to activate.")

        await close_db()

    asyncio.run(_run())


@pool.command("approve")
@click.option("--id", "entry_id", default=None, type=str, help="UUID of the suggestion to approve.")
@click.option("--all", "approve_all", is_flag=True, default=False, help="Approve all pending suggestions.")
def pool_approve(entry_id: str | None, approve_all: bool) -> None:
    """Approve pending LLM-suggested gene pool entries."""

    async def _run() -> None:
        from src.db.engine import get_session, close_db
        from src.db.queries import approve_suggestion, get_pending_suggestions

        async with get_session() as session:
            if approve_all:
                suggestions = await get_pending_suggestions(session)
                if not suggestions:
                    click.echo("No pending suggestions to approve.")
                    await close_db()
                    return
                for s in suggestions:
                    await approve_suggestion(session, s.id)
                    click.echo(f"  Approved: [{s.slot_name}] {s.slot_value}")
                click.echo(f"\n{len(suggestions)} suggestion(s) approved.")
            elif entry_id:
                result = await approve_suggestion(session, UUID(entry_id))
                if result:
                    click.echo(f"Approved: [{result.slot_name}] {result.slot_value}")
                else:
                    click.echo(f"Not found: {entry_id}")
            else:
                click.echo("Provide --id <UUID> or --all.")

        await close_db()

    asyncio.run(_run())


@pool.command("reject")
@click.option("--id", "entry_id", required=True, type=str, help="UUID of the suggestion to reject.")
def pool_reject(entry_id: str) -> None:
    """Reject a pending LLM-suggested gene pool entry."""

    async def _run() -> None:
        from src.db.engine import get_session, close_db
        from src.db.queries import reject_suggestion

        async with get_session() as session:
            success = await reject_suggestion(session, UUID(entry_id))

        if success:
            click.echo(f"Rejected: {entry_id}")
        else:
            click.echo(f"Not found: {entry_id}")

        await close_db()

    asyncio.run(_run())


# ---------------------------------------------------------------------------
# Variant approval queue
# ---------------------------------------------------------------------------


@cli.group()
def approve() -> None:
    """Review and approve/reject generated variants before deployment."""


@approve.command("list")
@click.option("--campaign-id", default=None, type=str, help="Filter by campaign UUID.")
def approve_list(campaign_id: str | None) -> None:
    """Show variants pending approval."""

    async def _run() -> None:
        from src.db.engine import get_session, close_db
        from src.db.queries import get_pending_approvals

        cid = UUID(campaign_id) if campaign_id else None

        async with get_session() as session:
            items = await get_pending_approvals(session, campaign_id=cid)

        if not items:
            click.echo("No variants pending approval.")
            await close_db()
            return

        click.echo(f"\n{len(items)} variant(s) pending approval:")
        click.echo("=" * 70)
        for item in items:
            click.echo(f"\n  ID: {item.id}")
            click.echo(f"  Variant: {item.variant_id}")
            click.echo(f"  Campaign: {item.campaign_id}")
            if item.hypothesis:
                click.echo(f"  Hypothesis: {item.hypothesis}")
            click.echo(f"  Submitted: {item.submitted_at}")
            genome = item.genome_snapshot
            if genome:
                click.echo("  Genome:")
                for k, v in sorted(genome.items()):
                    click.echo(f"    {k}: {v}")
            click.echo("-" * 70)

        click.echo(f"\nRun 'adagent approve yes --id <UUID>' to approve.")

        await close_db()

    asyncio.run(_run())


@approve.command("yes")
@click.option("--id", "approval_id", default=None, type=str, help="Approval queue item UUID.")
@click.option("--all", "approve_all", is_flag=True, default=False, help="Approve all pending variants.")
@click.option("--deploy-now", is_flag=True, default=False, help="Deploy approved variants immediately.")
@click.option("--campaign-id", default=None, type=str, help="Campaign UUID (required with --all).")
def approve_yes(approval_id: str | None, approve_all: bool, deploy_now: bool, campaign_id: str | None) -> None:
    """Approve pending variant(s) for deployment."""

    async def _run() -> None:
        from src.db.engine import get_session, close_db
        from src.db.queries import approve_variant as approve_variant_q, get_pending_approvals

        cid = UUID(campaign_id) if campaign_id else None

        async with get_session() as session:
            approved_items = []
            if approve_all:
                items = await get_pending_approvals(session, campaign_id=cid)
                if not items:
                    click.echo("No pending variants to approve.")
                    await close_db()
                    return
                for item in items:
                    result = await approve_variant_q(session, item.id)
                    if result:
                        approved_items.append(result)
                        click.echo(f"  Approved: {item.id}")
                click.echo(f"\n{len(approved_items)} variant(s) approved.")
            elif approval_id:
                result = await approve_variant_q(session, UUID(approval_id))
                if result:
                    approved_items.append(result)
                    click.echo(f"Approved: {approval_id}")
                else:
                    click.echo(f"Not found: {approval_id}")
            else:
                click.echo("Provide --id <UUID> or --all.")
                await close_db()
                return

            if deploy_now and approved_items:
                click.echo("\nDeploying approved variants...")
                from src.services.deployer import deploy_approved_variants

                # Determine campaign from the first approved item
                deploy_campaign_id = approved_items[0].campaign_id
                campaign_row = await session.execute(
                    __import__("sqlalchemy").select(
                        __import__("src.db.tables", fromlist=["Campaign"]).Campaign
                    ).where(
                        __import__("src.db.tables", fromlist=["Campaign"]).Campaign.id == deploy_campaign_id
                    )
                )
                campaign = campaign_row.scalar_one_or_none()
                if campaign:
                    adapter = _get_adapter(campaign.platform.value)
                    results = await deploy_approved_variants(session, adapter, deploy_campaign_id)
                    click.echo(f"Deployed {len(results)} variant(s).")
                else:
                    click.echo("Error: Campaign not found for deployment.")

        await close_db()

    asyncio.run(_run())


@approve.command("no")
@click.option("--id", "approval_id", required=True, type=str, help="Approval queue item UUID.")
@click.option("--reason", required=True, type=str, help="Rejection reason.")
def approve_no(approval_id: str, reason: str) -> None:
    """Reject a pending variant."""

    async def _run() -> None:
        from src.db.engine import get_session, close_db
        from src.db.queries import reject_variant as reject_variant_q

        async with get_session() as session:
            result = await reject_variant_q(session, UUID(approval_id), reason=reason)

        if result:
            click.echo(f"Rejected: {approval_id} — {reason}")
        else:
            click.echo(f"Not found: {approval_id}")

        await close_db()

    asyncio.run(_run())


@cli.command()
@click.option("--host", default="127.0.0.1", help="Host to bind to.")
@click.option("--port", default=8080, type=int, help="Port to listen on.")
def dashboard(host: str, port: int) -> None:
    """Start the read-only web dashboard."""
    import uvicorn

    from src.dashboard.app import app  # noqa: F811

    click.echo(f"Starting dashboard at http://{host}:{port}")
    uvicorn.run(app, host=host, port=port, log_level="info")


def main() -> None:
    """Package entry point."""
    cli()


if __name__ == "__main__":
    main()
