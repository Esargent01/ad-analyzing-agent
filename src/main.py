"""CLI entry point for the ad creative testing agent system."""

from __future__ import annotations

import asyncio
import json
import logging
import sys
from datetime import UTC
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
    """Return an adapter for a non-Meta platform.

    Meta adapters now route through
    :func:`src.adapters.meta_factory.get_meta_adapter_for_campaign`
    so callers can honour per-user OAuth tokens. This helper is
    kept only for ``google_ads`` and the mock fallback — calling it
    with ``platform == "meta"`` falls through to the mock adapter
    and emits a warning, which is the safe default for dev boxes
    without Google Ads credentials.
    """
    from src.adapters.mock import MockAdapter

    settings = get_settings()

    if platform == "google_ads":
        if (
            settings.google_ads_developer_token
            and not settings.google_ads_developer_token.startswith("placeholder")
        ):
            from src.adapters.google_ads import GoogleAdsAdapter

            return GoogleAdsAdapter(
                developer_token=settings.google_ads_developer_token,
                client_id=settings.google_ads_client_id,
                client_secret=settings.google_ads_client_secret,
                refresh_token=settings.google_ads_refresh_token,
                customer_id=settings.google_ads_customer_id,
            )
    elif platform == "meta":
        click.echo(
            "  Warning: _get_adapter called with platform='meta'; "
            "meta callers should use meta_factory instead. Falling back to MockAdapter."
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

        from src.adapters.meta_factory import get_meta_adapter_for_campaign
        from src.db.engine import _get_session_factory, close_db, get_session, init_db
        from src.db.tables import Campaign
        from src.exceptions import MetaConnectionMissing, MetaTokenExpired
        from src.services.ad_sync import sync_campaign_ads
        from src.services.orchestrator import Orchestrator

        settings = get_settings()
        await init_db()

        # Resolve the adapter inside the session so the factory can
        # read the campaign's owner (Phase C) and fetch the owning
        # user's encrypted token.
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

            if platform == "meta":
                try:
                    adapter = await get_meta_adapter_for_campaign(session, UUID(campaign_id))
                except MetaConnectionMissing as exc:
                    click.echo(f"Error: {exc}")
                    await close_db()
                    return
                except MetaTokenExpired as exc:
                    click.echo(
                        f"Error: {exc}\nThe campaign owner must reconnect Meta in the dashboard."
                    )
                    await close_db()
                    return
            else:
                adapter = _get_adapter(platform)

        # Sync any user-created Meta ads into ``deployments`` before
        # the orchestrator runs. Meta-only — other adapters don't have
        # a ``list_campaign_ads`` equivalent and the sync helper
        # early-returns on non-Meta campaigns anyway.
        if platform == "meta":
            try:
                async with get_session() as sync_session:
                    fresh = await sync_session.get(Campaign, UUID(campaign_id))
                    if fresh is not None:
                        n = await sync_campaign_ads(sync_session, fresh)
                        if n:
                            click.echo(
                                f"  + discovered {n} new ad(s) from Meta"
                            )
                        await sync_session.commit()
            except Exception as sync_exc:  # noqa: BLE001
                click.echo(
                    f"  ! ad sync failed ({sync_exc}); continuing"
                )

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


@cli.command(name="run-all-user-campaigns")
@click.option(
    "--dry-run",
    is_flag=True,
    default=False,
    help="List every candidate campaign without running a cycle.",
)
@click.option(
    "--with-generate",
    is_flag=True,
    default=False,
    help="Also run the generate + deploy phases for each campaign.",
)
@click.option(
    "--concurrency",
    default=3,
    type=int,
    help="Max number of campaigns to process concurrently (default 3).",
)
def run_all_user_campaigns(dry_run: bool, with_generate: bool, concurrency: int) -> None:
    """Run a monitoring cycle for every active, user-owned campaign.

    This is the daily cron entry point for the self-serve era. Fans
    out across every ``owner_user_id IS NOT NULL`` campaign that is
    still ``is_active = TRUE``, with per-campaign error isolation so
    one failure never stops the batch.

    Phase H: the loop is bounded by ``asyncio.Semaphore(concurrency)``
    so we don't hammer Meta's rate limits during fan-out, and the
    orchestrator now runs propose-only — the "act" phase queues
    proposals to ``approval_queue`` instead of mutating Meta. Users
    approve from the dashboard; the cron never pauses an ad.

    Expired-token handling: campaigns whose owner's Meta token has
    expired are skipped with a clear "skipped" log line and the user
    receives a "reconnect Meta" email from the next
    ``send-approval-digests`` pass. We don't spam them from this
    command directly.
    """

    async def _run() -> None:
        from sqlalchemy import select

        from src.adapters.meta_factory import get_meta_adapter_for_campaign
        from src.db.engine import _get_session_factory, close_db, get_session, init_db
        from src.db.tables import Campaign
        from src.exceptions import MetaConnectionMissing, MetaTokenExpired
        from src.services.ad_sync import sync_campaign_ads
        from src.services.orchestrator import Orchestrator

        settings = get_settings()
        await init_db()

        async with get_session() as session:
            stmt = (
                select(Campaign)
                .where(
                    Campaign.is_active.is_(True),
                    Campaign.owner_user_id.is_not(None),
                )
                .order_by(Campaign.name)
            )
            result = await session.execute(stmt)
            campaigns = list(result.scalars().all())

        if not campaigns:
            click.echo("No user-owned active campaigns found.")
            await close_db()
            return

        click.echo(
            f"Found {len(campaigns)} user-owned active campaign"
            f"{'' if len(campaigns) == 1 else 's'}:"
        )
        for c in campaigns:
            click.echo(f"  - {c.name} ({c.id})")

        if dry_run:
            click.echo("Dry run — no cycles executed.")
            await close_db()
            return

        session_factory = _get_session_factory()
        sem = asyncio.Semaphore(max(1, concurrency))
        logger = logging.getLogger(__name__)

        async def _one(campaign: Campaign) -> tuple[str, str | None]:
            """Run one campaign under the semaphore. Never raises.

            Returns ``(campaign_id, error_message or None)`` so the
            gather caller can tally successes/failures.
            """
            async with sem:
                click.echo(f"\n→ Running cycle for {campaign.name} ({campaign.id})")
                try:
                    async with get_session() as adapter_session:
                        try:
                            adapter = await get_meta_adapter_for_campaign(
                                adapter_session, campaign.id
                            )
                        except (MetaConnectionMissing, MetaTokenExpired) as exc:
                            click.echo(f"  ! skipped: {exc}")
                            return (str(campaign.id), f"skipped: {exc}")

                    # Sync new Meta-side ads into ``deployments`` before
                    # the orchestrator runs — without this, any ad the
                    # user created in Meta Ads Manager outside Kleiber
                    # stays invisible (poller is DB-driven). Isolated
                    # so sync failures don't break the cycle.
                    try:
                        async with get_session() as sync_session:
                            fresh = await sync_session.get(Campaign, campaign.id)
                            if fresh is not None:
                                n = await sync_campaign_ads(sync_session, fresh)
                                if n:
                                    click.echo(
                                        f"  + {campaign.name}: discovered "
                                        f"{n} new ad(s) from Meta"
                                    )
                                await sync_session.commit()
                    except Exception as sync_exc:  # noqa: BLE001
                        logger.warning(
                            "ad sync failed for %s: %s — continuing",
                            campaign.id, sync_exc,
                        )
                        click.echo(
                            f"  ! {campaign.name}: ad sync failed "
                            f"({sync_exc}); continuing"
                        )

                    orchestrator = Orchestrator(
                        adapter=adapter,
                        session_factory=session_factory,
                        settings=settings,
                    )
                    report = await orchestrator.run_cycle(
                        campaign.id, skip_generate=not with_generate
                    )
                    click.echo(
                        f"  ✓ {campaign.name}: cycle #{report.cycle_number} "
                        f"phase={report.phase_reached}"
                    )
                    if report.errors:
                        for phase, err in report.errors.items():
                            click.echo(f"    warning in {phase}: {err[:140]}")
                    return (str(campaign.id), None)
                except Exception as exc:  # noqa: BLE001
                    logger.exception("run-all-user-campaigns: cycle failed for %s", campaign.id)
                    click.echo(f"  ✗ {campaign.name}: {exc}")
                    return (str(campaign.id), str(exc))

        results = await asyncio.gather(*(_one(c) for c in campaigns))

        attempted = len(results)
        failed = [(cid, err) for cid, err in results if err is not None]
        succeeded = attempted - len(failed)

        click.echo(
            f"\nSummary: {attempted} attempted, {succeeded} succeeded, {len(failed)} failed."
        )
        if failed:
            click.echo("Failures:")
            for cid, err in failed:
                click.echo(f"  {cid}: {err[:200]}")

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


@cli.command(name="seed-dummy-approvals")
@click.option(
    "--campaign-name",
    default="Q2 Product Launch",
    help="Campaign name to attach the dummy proposals to.",
)
@click.option(
    "--campaign-id",
    default=None,
    type=str,
    help="Optional campaign UUID — overrides --campaign-name when provided.",
)
@click.option(
    "--copy-suggestions/--no-copy-suggestions",
    default=True,
    help="Also queue three dummy new_variant proposals with fresh copy.",
)
def seed_dummy_approvals(
    campaign_name: str,
    campaign_id: str | None,
    copy_suggestions: bool,
) -> None:
    """Seed pause + scale_budget + copy-suggestion proposals for layout debugging.

    Creates a dummy variant + deployment if the campaign has none, then
    queues approval_queue rows so the /experiments page renders the
    Phase H pause, scale, and new-variant cards. Safe to run multiple
    times — the pause/scale helpers dedupe per (deployment_id,
    action_type), and copy suggestions are tagged with a deterministic
    hypothesis prefix so re-runs skip them.
    """

    async def _run() -> None:
        from sqlalchemy import select
        from sqlalchemy import text as sa_text

        from src.db.engine import close_db, get_session, init_db
        from src.db.queries import (
            queue_pause_proposal,
            queue_scale_proposal,
            submit_for_approval,
        )
        from src.db.tables import (
            ApprovalActionType,
            ApprovalQueueItem,
            Campaign,
            Deployment,
            PlatformType,
            Variant,
            VariantStatus,
        )

        await init_db()
        async with get_session() as session:
            if campaign_id:
                stmt = select(Campaign).where(Campaign.id == UUID(campaign_id))
            else:
                stmt = select(Campaign).where(Campaign.name == campaign_name)
            campaign = (await session.execute(stmt)).scalar_one_or_none()
            if campaign is None:
                click.echo(
                    f"Error: campaign {'id ' + campaign_id if campaign_id else 'name ' + repr(campaign_name)} not found."
                )
                await close_db()
                return

            click.echo(f"Using campaign {campaign.id} ({campaign.name})")

            # Find or create an active deployment for the campaign so
            # the pause/scale rows reference real foreign keys. Exclude
            # V_DUMMY2 and prefer the oldest deployment so re-runs after
            # the secondary-dummy block is seeded keep targeting the
            # same primary deployment (otherwise the LIMIT 1 ordering
            # can flip between runs).
            existing = await session.execute(
                sa_text(
                    """
                    SELECT d.id, d.platform_ad_id, d.daily_budget, v.id, v.variant_code, v.genome
                    FROM deployments d
                    JOIN variants v ON v.id = d.variant_id
                    WHERE v.campaign_id = :cid
                      AND d.is_active = TRUE
                      AND v.variant_code <> 'V_DUMMY2'
                    ORDER BY d.created_at ASC
                    LIMIT 1
                    """
                ),
                {"cid": campaign.id},
            )
            row = existing.fetchone()
            if row is None:
                click.echo("No active deployment found — creating dummy variant + deployment.")
                dummy_genome = {
                    "headline": "Limited time: 40% off today only",
                    "subhead": "Join 12,000+ happy customers",
                    "cta_text": "Claim my discount",
                    "media_asset": "placeholder_lifestyle",
                    "audience": "retargeting_30d",
                }
                variant = Variant(
                    campaign_id=campaign.id,
                    variant_code="V_DUMMY",
                    genome=dummy_genome,
                    status=VariantStatus.active,
                    hypothesis="Dummy variant seeded for layout debugging.",
                )
                session.add(variant)
                await session.flush()

                deployment = Deployment(
                    variant_id=variant.id,
                    platform=PlatformType(campaign.platform.value),
                    platform_ad_id=f"dummy_ad_{variant.id.hex[:8]}",
                    daily_budget=Decimal("25.00"),
                    is_active=True,
                )
                session.add(deployment)
                await session.flush()

                deployment_id = deployment.id
                platform_ad_id = deployment.platform_ad_id
                current_budget = deployment.daily_budget
                genome = dummy_genome
                primary_variant_id = variant.id
            else:
                deployment_id = row[0]
                platform_ad_id = str(row[1])
                current_budget = Decimal(str(row[2]))
                primary_variant_id = row[3]
                genome = row[5] if isinstance(row[5], dict) else {}
                click.echo(f"Reusing deployment {deployment_id} ({platform_ad_id})")

            pause_id = await queue_pause_proposal(
                session,
                campaign_id=campaign.id,
                deployment_id=deployment_id,
                platform_ad_id=platform_ad_id,
                reason="statistically_significant_loser",
                evidence={
                    "reason": "statistically_significant_loser",
                    "variant_ctr": 0.0142,
                    "baseline_ctr": 0.0238,
                    "p_value": 0.0031,
                    "z_score": -2.96,
                    "impressions": 4820,
                    "clicks": 68,
                },
                genome_snapshot=genome,
            )
            if pause_id is None:
                click.echo("Pause proposal: skipped (open proposal already exists)")
            else:
                click.echo(f"Pause proposal: {pause_id}")

            scale_id = await queue_scale_proposal(
                session,
                campaign_id=campaign.id,
                deployment_id=deployment_id,
                platform_ad_id=platform_ad_id,
                current_budget=current_budget,
                proposed_budget=current_budget * Decimal("1.45"),
                evidence={
                    "allocation_method": "thompson_sampling",
                    "impressions": 6210,
                    "clicks": 184,
                    "posterior_mean": 0.0312,
                    "share_of_allocation": 0.42,
                },
                genome_snapshot=genome,
            )
            if scale_id is None:
                click.echo("Scale proposal: skipped (open proposal already exists)")
            else:
                click.echo(f"Scale proposal: {scale_id}")

            if copy_suggestions:
                # Three plausible copy variations the "generator" might
                # propose — each changes exactly one slot (headline /
                # subhead / cta_text) from the running genome so the UI
                # shows one-element-at-a-time hypotheses.
                base = (
                    genome
                    if isinstance(genome, dict) and genome
                    else {
                        "headline": "Limited time: 40% off today only",
                        "subhead": "Join 12,000+ happy customers",
                        "cta_text": "Claim my discount",
                        "media_asset": "placeholder_lifestyle",
                        "audience": "retargeting_30d",
                    }
                )
                suggestions = [
                    {
                        "genome": {**base, "headline": "Only 24 hours left — 40% off everything"},
                        "hypothesis": (
                            "[dummy-seed] Time-boxed urgency language should "
                            "lift CTR over the evergreen 'limited time' phrasing."
                        ),
                    },
                    {
                        "genome": {**base, "subhead": "Rated 4.9★ by 12,000+ customers"},
                        "hypothesis": (
                            "[dummy-seed] Replacing the raw count with a star "
                            "rating adds trust signal density on the subhead."
                        ),
                    },
                    {
                        "genome": {**base, "cta_text": "Start saving today"},
                        "hypothesis": (
                            "[dummy-seed] Outcome-focused CTA ('start saving') "
                            "tests better than transaction-focused ('claim')."
                        ),
                    },
                ]

                # Dedupe on the hypothesis prefix so re-running the
                # command doesn't stack up duplicate copy suggestions.
                existing_hypotheses = await session.execute(
                    sa_text(
                        """
                        SELECT hypothesis FROM approval_queue
                        WHERE campaign_id = :cid
                          AND action_type = 'new_variant'
                          AND approved IS NULL
                          AND hypothesis LIKE '[dummy-seed]%'
                        """
                    ),
                    {"cid": campaign.id},
                )
                existing_set = {str(r[0]) for r in existing_hypotheses.fetchall()}

                queued = 0
                for suggestion in suggestions:
                    if suggestion["hypothesis"] in existing_set:
                        continue
                    code_row = await session.execute(
                        sa_text("SELECT next_variant_code(:id)"),
                        {"id": campaign.id},
                    )
                    variant_code = str(code_row.scalar_one())
                    proposal_variant = Variant(
                        campaign_id=campaign.id,
                        variant_code=variant_code,
                        genome=suggestion["genome"],
                        status=VariantStatus.pending,
                        hypothesis=suggestion["hypothesis"],
                    )
                    session.add(proposal_variant)
                    await session.flush()

                    item = await submit_for_approval(
                        session,
                        variant_id=proposal_variant.id,
                        campaign_id=campaign.id,
                        genome=suggestion["genome"],
                        hypothesis=suggestion["hypothesis"],
                    )
                    click.echo(
                        f"Copy suggestion {variant_code}: {item.id} "
                        f"({suggestion['hypothesis'][:60]}…)"
                    )
                    queued += 1
                if queued == 0:
                    click.echo("Copy suggestions: skipped (already seeded)")
                else:
                    click.echo(f"Copy suggestions queued: {queued}")

            # ---- Secondary dummy: fatigue pause + scale-DOWN on a
            # distinct deployment so we can show the other half of the
            # state space (audience-fatigue vs stat-sig, scale-down vs
            # scale-up). The pause/scale queue helpers dedupe per
            # (deployment_id, action_type), so we need a second
            # deployment rather than reusing V_DUMMY.
            secondary_code = "V_DUMMY2"
            secondary_stmt = select(Variant).where(
                Variant.campaign_id == campaign.id,
                Variant.variant_code == secondary_code,
            )
            secondary_variant = (await session.execute(secondary_stmt)).scalar_one_or_none()
            if secondary_variant is None:
                secondary_genome = {
                    "headline": "Fresh arrivals — see what's new",
                    "subhead": "Curated weekly drops",
                    "cta_text": "Shop new arrivals",
                    "media_asset": "placeholder_lifestyle",
                    "audience": "broad_interest",
                }
                secondary_variant = Variant(
                    campaign_id=campaign.id,
                    variant_code=secondary_code,
                    genome=secondary_genome,
                    status=VariantStatus.active,
                    hypothesis="Secondary dummy variant — fatigue + scale-down demos.",
                )
                session.add(secondary_variant)
                await session.flush()

                secondary_deployment = Deployment(
                    variant_id=secondary_variant.id,
                    platform=PlatformType(campaign.platform.value),
                    platform_ad_id=f"dummy_ad_{secondary_variant.id.hex[:8]}",
                    daily_budget=Decimal("40.00"),
                    is_active=True,
                )
                session.add(secondary_deployment)
                await session.flush()
                secondary_deployment_id = secondary_deployment.id
                secondary_platform_ad_id = secondary_deployment.platform_ad_id
                secondary_budget = secondary_deployment.daily_budget
                secondary_genome_used: dict = secondary_genome
            else:
                dep_row = await session.execute(
                    sa_text(
                        """
                        SELECT id, platform_ad_id, daily_budget
                        FROM deployments
                        WHERE variant_id = :vid AND is_active = TRUE
                        LIMIT 1
                        """
                    ),
                    {"vid": secondary_variant.id},
                )
                dep = dep_row.fetchone()
                if dep is None:
                    backfill_deployment = Deployment(
                        variant_id=secondary_variant.id,
                        platform=PlatformType(campaign.platform.value),
                        platform_ad_id=f"dummy_ad_{secondary_variant.id.hex[:8]}",
                        daily_budget=Decimal("40.00"),
                        is_active=True,
                    )
                    session.add(backfill_deployment)
                    await session.flush()
                    secondary_deployment_id = backfill_deployment.id
                    secondary_platform_ad_id = backfill_deployment.platform_ad_id
                    secondary_budget = backfill_deployment.daily_budget
                else:
                    secondary_deployment_id = dep[0]
                    secondary_platform_ad_id = str(dep[1])
                    secondary_budget = Decimal(str(dep[2]))
                secondary_genome_used = (
                    secondary_variant.genome if isinstance(secondary_variant.genome, dict) else {}
                )

            fatigue_id = await queue_pause_proposal(
                session,
                campaign_id=campaign.id,
                deployment_id=secondary_deployment_id,
                platform_ad_id=secondary_platform_ad_id,
                reason="audience_fatigue",
                evidence={
                    "reason": "audience_fatigue",
                    "consecutive_decline_days": 4,
                    "trend_slope": -0.0012,
                    "impressions": 8120,
                    "clicks": 98,
                },
                genome_snapshot=secondary_genome_used,
            )
            if fatigue_id is None:
                click.echo("Fatigue pause proposal: skipped (open proposal already exists)")
            else:
                click.echo(f"Fatigue pause proposal: {fatigue_id}")

            scale_down_id = await queue_scale_proposal(
                session,
                campaign_id=campaign.id,
                deployment_id=secondary_deployment_id,
                platform_ad_id=secondary_platform_ad_id,
                current_budget=secondary_budget,
                proposed_budget=secondary_budget * Decimal("0.55"),
                evidence={
                    "allocation_method": "thompson_sampling",
                    "impressions": 3140,
                    "clicks": 41,
                    "posterior_mean": 0.0131,
                    "share_of_allocation": 0.08,
                },
                genome_snapshot=secondary_genome_used,
            )
            if scale_down_id is None:
                click.echo("Scale-down proposal: skipped (open proposal already exists)")
            else:
                click.echo(f"Scale-down proposal: {scale_down_id}")

            # ---- Promote-winner proposal on the primary V_DUMMY variant.
            # ``src.db.queries`` doesn't have a helper for this yet — the
            # orchestrator currently flips winner status directly rather
            # than queueing a proposal — so we insert the row inline and
            # dedupe with a manual SELECT on open promote_winner rows.
            existing_promote = await session.execute(
                sa_text(
                    """
                    SELECT id FROM approval_queue
                    WHERE campaign_id = :cid
                      AND action_type = 'promote_winner'
                      AND approved IS NULL
                    LIMIT 1
                    """
                ),
                {"cid": campaign.id},
            )
            if existing_promote.first() is None:
                promote_item = ApprovalQueueItem(
                    variant_id=primary_variant_id,
                    campaign_id=campaign.id,
                    genome_snapshot=genome or {},
                    hypothesis=(
                        "[dummy-seed] Promote this variant to winner — "
                        "CTR has held above baseline for 6 consecutive "
                        "days with p < 0.01 on the significance test."
                    ),
                    action_type=ApprovalActionType.promote_winner,
                    action_payload={},
                )
                session.add(promote_item)
                await session.flush()
                click.echo(f"Promote-winner proposal: {promote_item.id}")
            else:
                click.echo("Promote-winner proposal: skipped (open proposal already exists)")

            await session.commit()

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
            # Check table counts using ORM models (no raw SQL interpolation)
            from sqlalchemy import func as sa_func

            from src.db.tables import (
                Campaign as CampaignModel,
            )
            from src.db.tables import (
                Deployment as DeploymentModel,
            )
            from src.db.tables import (
                GenePoolEntry,
            )
            from src.db.tables import (
                Metric as MetricModel,
            )
            from src.db.tables import (
                Variant as VariantModel,
            )

            _health_tables: list[tuple[str, type]] = [
                ("gene_pool", GenePoolEntry),
                ("campaigns", CampaignModel),
                ("variants", VariantModel),
                ("deployments", DeploymentModel),
                ("metrics", MetricModel),
            ]
            for label, model in _health_tables:
                row = await session.execute(select(sa_func.count()).select_from(model))
                count = row.scalar_one()
                click.echo(f"  {label}: {count} rows")

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
                    click.echo(f"  Expired {expired_count} stale proposal(s) (>14 days old)")
                if generation_paused:
                    click.echo("  Generation paused — approval queue at capacity")
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
        click.echo(f"\n{'=' * 60}")
        click.echo(f"WEEKLY REPORT — {campaign_name}")
        click.echo(f"{'=' * 60}")
        click.echo(f"Period: {report.week_start} to {report.week_end}")
        click.echo(f"Cycles completed: {report.cycles_run}")
        click.echo(f"Variants launched: {report.variants_launched}")
        click.echo("\nFull-Funnel Metrics:")
        click.echo(f"  Impressions: {report.total_impressions:,}")
        click.echo(f"  Reach: {report.total_reach:,}")
        click.echo(
            f"  Video Views (3s): {report.total_video_views_3s:,}  Hook Rate: {report.avg_hook_rate:.1%}"
        )
        click.echo(
            f"  Video Views (15s): {report.total_video_views_15s:,}  Hold Rate: {report.avg_hold_rate:.1%}"
        )
        click.echo(f"  Link Clicks: {report.total_link_clicks:,}  CTR: {report.avg_ctr:.2%}")
        click.echo(f"  Landing Page Views: {report.total_landing_page_views:,}")
        click.echo(f"  Add to Carts: {report.total_add_to_carts:,}")
        click.echo(f"  Purchases: {report.total_purchases:,}")
        click.echo(f"  Revenue: ${report.total_purchase_value:,.2f}")
        click.echo("\nEfficiency:")
        click.echo(f"  Spend: ${report.total_spend:,.2f}")
        click.echo(f"  CPM: ${report.avg_cpm:,.2f}")
        click.echo(f"  CPA: {f'${report.avg_cpa:,.2f}' if report.avg_cpa else 'N/A'}")
        click.echo(
            f"  Cost/Purchase: {f'${report.avg_cost_per_purchase:,.2f}' if report.avg_cost_per_purchase else 'N/A'}"
        )
        click.echo(f"  ROAS: {f'{report.avg_roas:.2f}x' if report.avg_roas else 'N/A'}")
        click.echo(f"  Frequency: {report.avg_frequency:.1f}")

        best_variant = report.best_variant
        worst_variant = report.worst_variant
        if best_variant:
            roas_str = (
                f"ROAS {best_variant.roas:.2f}x"
                if best_variant.roas
                else f"CTR {best_variant.ctr:.2%}"
            )
            click.echo(f"\nBest: {best_variant.variant_code} — {roas_str}")
        if worst_variant:
            roas_str = (
                f"ROAS {worst_variant.roas:.2f}x"
                if worst_variant.roas
                else f"CTR {worst_variant.ctr:.2%}"
            )
            click.echo(f"Worst: {worst_variant.variant_code} — {roas_str}")

        if report.top_elements:
            click.echo("\nTop Elements:")
            for el in report.top_elements[:10]:
                roas_str = f" ROAS {el.avg_roas:.2f}x" if el.avg_roas else ""
                click.echo(
                    f"  {el.slot_name}: {el.slot_value} — CTR {el.avg_ctr:.2%}{roas_str} ({el.variants_tested} variants)"
                )

        if report.proposed_variants:
            click.echo(f"\nNext week's experiments ({len(report.proposed_variants)} proposed):")
            for pv in report.proposed_variants:
                badge = (
                    f" [expires in {pv.days_until_expiry}d]"
                    if pv.classification == "expiring_soon"
                    else ""
                )
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
                    dashboard_url=(
                        f"{settings.frontend_base_url.rstrip('/')}"
                        f"/campaigns/{campaign_id}/reports/weekly/"
                        f"{report.week_start.isoformat()}"
                    ),
                )
                if success:
                    click.echo(f"\nEmail report sent to {settings.report_email_to}")
                else:
                    click.echo("\nFailed to send email report. Check logs.")

        # Send via Slack if configured
        if settings.slack_webhook_url and not settings.slack_webhook_url.startswith(
            "https://hooks.slack.com/services/PLACEHOLDER"
        ):
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
        from src.reports.web import render_index
        from src.reports.web import render_weekly_report as render_weekly_html

        html_path = render_weekly_html(report, campaign_name, week_label)
        click.echo(f"\nWeb report: {html_path}")

        # Update index
        from pathlib import Path as _Path

        public_dir = _Path(settings.report_output_dir)
        daily_dates = sorted(
            [p.stem for p in (public_dir / "daily").glob("*.html")]
            if (public_dir / "daily").exists()
            else [],
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
@click.option(
    "--send-email/--no-send-email", default=True, help="Send report via email (default: True)."
)
@click.option(
    "--report-date",
    default=None,
    type=str,
    help="Date to report on (YYYY-MM-DD). Defaults to yesterday.",
)
def daily_report(campaign_id: str, send_email: bool, report_date: str | None) -> None:
    """Generate and send a daily performance report for a campaign.

    Reports on a single calendar day (defaults to yesterday).
    """

    async def _run() -> None:
        from datetime import date, timedelta

        from src.adapters.meta_factory import get_meta_adapter_for_campaign
        from src.db.engine import close_db, get_session, init_db
        from src.services.poller import MetricsPoller
        from src.services.reports import build_daily_report

        settings = get_settings()
        await init_db()

        # Report on a single calendar day — yesterday by default
        if report_date:
            report_day = date.fromisoformat(report_date)
        else:
            report_day = date.today() - timedelta(days=1)

        campaign_uuid = UUID(campaign_id)

        # Re-poll Meta for the report day's settled numbers before building
        # the aggregate. Without this, the report only sees whatever partial
        # current-day snapshot the live cron wrote. Non-fatal on failure.
        try:
            async with get_session() as session:
                adapter = await get_meta_adapter_for_campaign(session, campaign_uuid)
                poller = MetricsPoller(adapter=adapter, session=session)
                await poller.poll_campaign_for_date(campaign_uuid, report_day)
                await session.commit()
        except Exception as poll_exc:  # noqa: BLE001
            click.echo(
                f"Warning: settled-metrics backfill for {report_day.isoformat()} "
                f"failed ({poll_exc}); rendering from existing data"
            )

        v2_report = None
        async with get_session() as session:
            try:
                v2_report = await build_daily_report(session, campaign_uuid, report_day)
            except LookupError:
                click.echo(f"Error: Campaign {campaign_id} not found.")
                await close_db()
                return

        campaign_name = v2_report.campaign_name

        # Print to console
        click.echo(f"\n{'=' * 60}")
        click.echo(f"DAILY REPORT — {campaign_name}")
        click.echo(f"{'=' * 60}")
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
            total_video_views_15s / total_video_views_3s if total_video_views_3s > 0 else 0.0
        )
        avg_ctr_f = total_clicks / total_impressions if total_impressions > 0 else 0.0
        avg_cpm_f = (
            float(v2_report.total_spend) / total_impressions * 1000
            if total_impressions > 0
            else 0.0
        )
        avg_frequency_f = total_impressions / total_reach if total_reach > 0 else 0.0

        click.echo("\nFull-Funnel Metrics:")
        click.echo(f"  Impressions: {total_impressions:,}")
        click.echo(f"  Reach: {total_reach:,}")
        click.echo(
            f"  Video Views (3s): {total_video_views_3s:,}  Hook Rate: {avg_hook_rate_f:.1%}"
        )
        click.echo(
            f"  Video Views (15s): {total_video_views_15s:,}  Hold Rate: {avg_hold_rate_f:.1%}"
        )
        click.echo(f"  Link Clicks: {total_clicks:,}  CTR: {avg_ctr_f:.2%}")
        click.echo(f"  Landing Page Views: {total_landing_page_views:,}")
        click.echo(f"  Add to Carts: {total_add_to_carts:,}")
        click.echo(f"  Purchases: {v2_report.total_purchases:,}")
        click.echo(f"  Revenue: ${total_purchase_value:,.2f}")
        click.echo("\nEfficiency:")
        click.echo(f"  Spend: ${v2_report.total_spend:,.2f}")
        click.echo(f"  CPM: ${avg_cpm_f:,.2f}")
        cpa_str = (
            f"${v2_report.avg_cost_per_purchase:,.2f}" if v2_report.avg_cost_per_purchase else "N/A"
        )
        click.echo(f"  Cost/Purchase: {cpa_str}")
        click.echo(f"  ROAS: {f'{v2_report.avg_roas:.2f}x' if v2_report.avg_roas else 'N/A'}")
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
                    v2_report,
                    base_url=settings.report_base_url,
                    dashboard_url=(
                        f"{settings.frontend_base_url.rstrip('/')}"
                        f"/campaigns/{campaign_id}/reports/daily/"
                        f"{v2_report.report_date.isoformat()}"
                    ),
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
            [p.stem for p in (public_dir / "weekly").glob("*.html")]
            if (public_dir / "weekly").exists()
            else [],
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
                weighted_avg = (
                    sum(c * i for c, i, _ in entries) / total_imps if total_imps > 0 else 0.0
                )
                _, _, confidence = element_significance(
                    element_ctrs=ctrs, global_mean_ctr=global_mean_ctr
                )

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


@cli.command(name="backfill-media-type")
@click.option("--campaign-id", required=True, type=str, help="Local campaign UUID.")
def backfill_media_type(campaign_id: str) -> None:
    """Refresh ``variants.media_type`` from Meta for every variant in a campaign.

    Existing variants imported before ``variants.media_type`` existed
    sit at ``'unknown'`` — the reporting layer treats that as a safe
    default (shows the full funnel) so nothing's broken, but the
    video-only metric rows leak onto image campaigns until we fill the
    column in.

    This command calls ``MetaAdapter.list_campaign_ads`` once against
    the campaign's Meta id, pulls ``object_type`` from each creative,
    and writes the mapped ``media_type`` (video/image/mixed/unknown)
    onto each matching variant keyed by its deployment's
    ``platform_ad_id``. Idempotent — re-running is safe and picks up
    any Meta-side creative type changes.

    Example::

        python -m src.main backfill-media-type --campaign-id <uuid>
    """

    async def _run() -> None:
        from sqlalchemy import text as sa_text

        from src.adapters.meta_factory import get_meta_adapter_for_campaign
        from src.db.engine import close_db, get_session, init_db

        try:
            campaign_uuid = UUID(campaign_id)
        except ValueError:
            click.echo(f"Error: {campaign_id!r} is not a valid UUID.")
            return

        await init_db()
        try:
            async with get_session() as session:
                campaign_row = await session.execute(
                    sa_text(
                        """
                        SELECT c.id, c.name, c.platform_campaign_id,
                               c.meta_ad_account_id, c.meta_page_id,
                               c.landing_page_url, c.owner_user_id
                        FROM campaigns c
                        WHERE c.id = :id
                        """
                    ),
                    {"id": str(campaign_uuid)},
                )
                campaign = campaign_row.first()
                if campaign is None:
                    click.echo(f"Error: campaign {campaign_id} not found.")
                    return
                if not campaign.platform_campaign_id:
                    click.echo(
                        f"Error: campaign {campaign.name!r} has no "
                        "platform_campaign_id — not a Meta-imported campaign."
                    )
                    return

                adapter = await get_meta_adapter_for_campaign(
                    session, campaign_uuid
                )
                ads = await adapter.list_campaign_ads(
                    str(campaign.platform_campaign_id)
                )
                click.echo(
                    f"Fetched {len(ads)} ads from Meta for campaign "
                    f"{campaign.name!r}."
                )

                # Map platform_ad_id → media_type for quick lookup.
                by_ad_id: dict[str, str] = {
                    str(ad.get("ad_id") or ""): str(
                        ad.get("media_type") or "unknown"
                    )
                    for ad in ads
                }

                # Join variants → deployments → filter by campaign.
                rows = await session.execute(
                    sa_text(
                        """
                        SELECT v.id, v.variant_code, d.platform_ad_id,
                               v.media_type
                        FROM variants v
                        JOIN deployments d ON d.variant_id = v.id
                        WHERE v.campaign_id = :id
                        """
                    ),
                    {"id": str(campaign_uuid)},
                )

                updated = 0
                skipped = 0
                for row in rows.fetchall():
                    variant_id = row[0]
                    variant_code = row[1]
                    platform_ad_id = str(row[2]) if row[2] else ""
                    current = str(row[3] or "unknown")
                    new_type = by_ad_id.get(platform_ad_id, "unknown")
                    if new_type == current:
                        skipped += 1
                        continue
                    await session.execute(
                        sa_text(
                            "UPDATE variants SET media_type = :mt "
                            "WHERE id = :vid"
                        ),
                        {"mt": new_type, "vid": variant_id},
                    )
                    click.echo(
                        f"  {variant_code}: {current} → {new_type}"
                    )
                    updated += 1

                await session.commit()
                click.echo(
                    f"Done. Updated {updated}, skipped {skipped} "
                    "(already correct)."
                )
        finally:
            await close_db()

    asyncio.run(_run())


@cli.command(name="set-campaign-objective")
@click.option("--campaign-id", required=True, type=str, help="Local campaign UUID.")
@click.option(
    "--objective",
    required=True,
    type=click.Choice(
        [
            "OUTCOME_SALES",
            "OUTCOME_LEADS",
            "OUTCOME_ENGAGEMENT",
            "OUTCOME_TRAFFIC",
            "OUTCOME_AWARENESS",
            "OUTCOME_APP_PROMOTION",
            "OUTCOME_UNKNOWN",
        ],
        case_sensitive=True,
    ),
    help="Canonical ODAX objective to set.",
)
def set_campaign_objective(campaign_id: str, objective: str) -> None:
    """Force a campaign's ``objective`` column to a specific ODAX value.

    Useful for demo / QA workflows where you want to inspect how the
    same underlying metrics render under different objective lenses
    without editing the campaign on Meta's side. The opportunistic
    re-sync in ``sync_campaign_ads`` will overwrite this value on the
    next cron tick — rerun this command after each tick if you want
    to keep the override pinned.

    Example::

        python -m src.main set-campaign-objective \\
            --campaign-id <uuid> --objective OUTCOME_LEADS
    """

    async def _run() -> None:
        from sqlalchemy import text as sa_text

        from src.db.engine import close_db, get_session, init_db

        try:
            campaign_uuid = UUID(campaign_id)
        except ValueError:
            click.echo(f"Error: {campaign_id!r} is not a valid UUID.")
            return

        await init_db()
        try:
            async with get_session() as session:
                prev_row = await session.execute(
                    sa_text("SELECT name, objective FROM campaigns WHERE id = :id"),
                    {"id": str(campaign_uuid)},
                )
                prev = prev_row.first()
                if prev is None:
                    click.echo(f"Error: campaign {campaign_id} not found.")
                    return

                if prev[1] == objective:
                    click.echo(
                        f"{prev[0]}: already {objective} — no change."
                    )
                    return

                await session.execute(
                    sa_text(
                        "UPDATE campaigns SET objective = :obj WHERE id = :id"
                    ),
                    {"obj": objective, "id": str(campaign_uuid)},
                )
                await session.commit()
                click.echo(f"{prev[0]}: {prev[1]} → {objective}")
        finally:
            await close_db()

    asyncio.run(_run())


@cli.command(name="backfill-campaign-objective")
@click.option(
    "--dry-run",
    is_flag=True,
    default=False,
    help="List planned updates without writing.",
)
def backfill_campaign_objective(dry_run: bool) -> None:
    """Refresh ``campaigns.objective`` from Meta for every imported campaign.

    Campaigns imported before migration 017 landed carry the default
    ``OUTCOME_SALES`` — a safe placeholder that keeps today's reports
    rendering, but wrong for Leads / Engagement / Traffic / Awareness
    advertisers. This command re-reads the live objective from Meta for
    every campaign still at the default and persists the mapped ODAX
    value.

    The opportunistic re-sync in ``sync_campaign_ads`` eventually
    backfills the same data on the next cron tick per campaign, so
    this CLI is optional — run it once post-deploy to avoid waiting a
    day per campaign.

    Scope: only Meta campaigns with a ``platform_campaign_id`` are
    touched. Idempotent — re-running after every campaign has a real
    objective is a no-op.

    Example::

        python -m src.main backfill-campaign-objective
        python -m src.main backfill-campaign-objective --dry-run
    """

    async def _run() -> None:
        from sqlalchemy import text as sa_text

        from src.adapters.meta_factory import get_meta_adapter_for_campaign
        from src.db.engine import close_db, get_session, init_db

        await init_db()
        try:
            async with get_session() as session:
                rows = await session.execute(
                    sa_text(
                        """
                        SELECT id, name, platform_campaign_id, objective
                        FROM campaigns
                        WHERE platform = 'meta'
                          AND platform_campaign_id IS NOT NULL
                          AND objective = 'OUTCOME_SALES'
                        ORDER BY created_at
                        """
                    )
                )
                candidates = rows.fetchall()
                if not candidates:
                    click.echo("No campaigns to backfill.")
                    return

                click.echo(
                    f"Checking objective for {len(candidates)} campaign(s)…"
                )
                updated = 0
                skipped = 0
                failed = 0

                for row in candidates:
                    local_id: UUID = row[0]
                    name: str = row[1]
                    meta_id: str = str(row[2])
                    current: str = row[3]

                    try:
                        adapter = await get_meta_adapter_for_campaign(
                            session, local_id
                        )
                        fresh = await adapter.get_campaign_objective(meta_id)
                    except Exception as exc:  # noqa: BLE001
                        click.echo(f"  ! {name}: {exc}")
                        failed += 1
                        continue

                    if fresh == current or not fresh:
                        skipped += 1
                        continue

                    click.echo(f"  {name}: {current} → {fresh}")
                    if not dry_run:
                        await session.execute(
                            sa_text(
                                "UPDATE campaigns SET objective = :obj "
                                "WHERE id = :id"
                            ),
                            {"obj": fresh, "id": str(local_id)},
                        )
                    updated += 1

                if not dry_run:
                    await session.commit()
                click.echo(
                    f"Done. Updated {updated}, skipped {skipped}, "
                    f"failed {failed}."
                    + (" (dry run — no writes)" if dry_run else "")
                )
        finally:
            await close_db()

    asyncio.run(_run())


@cli.command()
@click.option("--campaign-id", required=True, type=str, help="Local campaign UUID.")
@click.option(
    "--date-preset", default="last_30d", help="Meta date preset (last_7d, last_30d, etc.)."
)
@click.option(
    "--ad-account-id", default=None, type=str, help="Override Meta ad account ID (e.g. act_123456)."
)
@click.option(
    "--dry-run", is_flag=True, default=False, help="Preview what would be imported without writing."
)
@click.option(
    "--refresh-metrics",
    is_flag=True,
    default=False,
    help="Re-fetch and update metrics for already-imported ads.",
)
def import_meta_ads(
    campaign_id: str,
    date_preset: str,
    ad_account_id: str | None,
    dry_run: bool,
    refresh_metrics: bool,
) -> None:
    """Import existing Meta ads and their historical metrics into the system.

    Discovers all ads in the Meta campaign linked to CAMPAIGN_ID,
    creates variant records, and backfills daily metrics snapshots.
    """

    async def _run() -> None:
        import json
        import uuid
        from datetime import datetime

        from sqlalchemy import text as sa_text

        from src.adapters.meta_factory import get_meta_adapter_for_campaign
        from src.db.engine import close_db, get_session, init_db
        from src.exceptions import MetaConnectionMissing, MetaTokenExpired

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
                click.echo(
                    "Error: Campaign has no platform_campaign_id set. "
                    "Update it with the Meta campaign ID first."
                )
                await close_db()
                return

            # 2. Resolve adapter through the per-user factory (falls back
            # to the global token for legacy campaigns without an owner).
            try:
                adapter = await get_meta_adapter_for_campaign(session, UUID(campaign_id))
            except (MetaConnectionMissing, MetaTokenExpired) as exc:
                click.echo(f"Error: {exc}")
                await close_db()
                return

            # Optional per-invocation override of the ad account so
            # operators can target a different account than the
            # owner's default (useful for legacy support).
            if ad_account_id:
                from facebook_business.adobjects.adaccount import AdAccount

                adapter._ad_account_id = ad_account_id  # type: ignore[attr-defined]
                adapter._account = AdAccount(ad_account_id)  # type: ignore[attr-defined]

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
                    click.echo(
                        f"  Skipping {ad_id} (already imported, use --refresh-metrics to update)"
                    )
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
                                ad_id,
                                date_preset=date_preset,
                            )
                            for day in daily_metrics:
                                if int(day["impressions"]) == 0:
                                    continue
                                day_ts = datetime.strptime(
                                    str(day["date_start"]), "%Y-%m-%d"
                                ).replace(hour=23, minute=59, tzinfo=UTC)

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
                                        "purchase_value": Decimal(
                                            str(day.get("purchase_value", 0))
                                        ),
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
                        ad_id,
                        date_preset=date_preset,
                    )
                    for day in daily_metrics:
                        if int(day["impressions"]) == 0:
                            continue
                        # Parse the date into a timestamp
                        day_ts = datetime.strptime(str(day["date_start"]), "%Y-%m-%d").replace(
                            hour=23, minute=59, tzinfo=UTC
                        )

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

        from src.adapters.meta_factory import get_meta_adapter_for_campaign
        from src.db.engine import close_db, get_session, init_db
        from src.exceptions import MetaConnectionMissing, MetaTokenExpired

        await init_db()

        async with get_session() as session:
            # Verify campaign exists and pull its per-campaign ad
            # account id so the fallback path below can echo a useful
            # value when no override is supplied.
            row = await session.execute(
                sa_text("SELECT platform, meta_ad_account_id FROM campaigns WHERE id = :id"),
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

            campaign_ad_account_id = campaign[1]

            # Resolve adapter through the per-user factory. The factory
            # reads the campaign's ``meta_ad_account_id`` / ``meta_page_id``
            # columns (Phase G) and passes them through, so the adapter
            # is already scoped to the right account without touching
            # global settings.
            try:
                adapter = await get_meta_adapter_for_campaign(session, UUID(campaign_id))
            except (MetaConnectionMissing, MetaTokenExpired) as exc:
                click.echo(f"Error: {exc}")
                await close_db()
                return

            # Optional override: operators can point at a different
            # ad account than the one on the campaign row (legacy
            # repair path; not used in normal operation).
            if ad_account_id:
                from facebook_business.adobjects.adaccount import AdAccount

                adapter._ad_account_id = ad_account_id  # type: ignore[attr-defined]
                adapter._account = AdAccount(ad_account_id)  # type: ignore[attr-defined]

            effective_account = ad_account_id or campaign_ad_account_id
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
                click.echo(
                    f"  [{i}] [{asset.asset_type.upper()}] {asset.name} {size_info}{dur_info}"
                )
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
    "headline",
    "subhead",
    "cta_text",
    "media_asset",
    "audience",
]


@cli.group()
def pool() -> None:
    """Manage the gene pool — creative elements available for testing."""


@pool.command("add")
@click.option("--slot", required=True, type=click.Choice(VALID_SLOTS), help="Slot name.")
@click.option("--value", required=True, type=str, help="Slot value to add.")
@click.option("--description", default=None, type=str, help="Human-readable description.")
@click.option(
    "--meta-audience-id",
    default=None,
    type=str,
    help="Meta custom audience ID (audience slot only).",
)
def pool_add(slot: str, value: str, description: str | None, meta_audience_id: str | None) -> None:
    """Add a new entry to the gene pool."""

    async def _run() -> None:
        from src.db.engine import close_db, get_session
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
        from src.db.engine import close_db, get_session
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
                click.echo(
                    f"\n{current_slot.upper()} ({sum(1 for e in entries if e.slot_name == current_slot)} entries)"
                )
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
        from src.db.engine import close_db, get_session
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
@click.option(
    "--slot",
    default=None,
    type=click.Choice(["headline", "subhead", "cta_text"]),
    help="Slot to suggest for (default: all text slots).",
)
@click.option(
    "--brand-context", default=None, type=str, help="Brand voice / product description for context."
)
@click.option("--count", default=5, type=int, help="Number of suggestions to generate.")
@click.option(
    "--campaign-id",
    default=None,
    type=str,
    help="Campaign UUID for performance-informed suggestions.",
)
def pool_suggest(
    slot: str | None, brand_context: str | None, count: int, campaign_id: str | None
) -> None:
    """Use the LLM to suggest new creative text for the gene pool."""

    async def _run() -> None:
        from src.agents.copywriter import CopywriterAgent
        from src.db.engine import close_db, get_session
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
            click.echo(
                "Run 'adagent pool review' to see them, 'adagent pool approve --all' to activate."
            )

        await close_db()

    asyncio.run(_run())


@pool.command("review")
def pool_review() -> None:
    """List pending LLM-suggested gene pool entries awaiting approval."""

    async def _run() -> None:
        from src.db.engine import close_db, get_session
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

        click.echo("\nRun 'adagent pool approve --id <UUID>' to activate.")

        await close_db()

    asyncio.run(_run())


@pool.command("approve")
@click.option("--id", "entry_id", default=None, type=str, help="UUID of the suggestion to approve.")
@click.option(
    "--all", "approve_all", is_flag=True, default=False, help="Approve all pending suggestions."
)
def pool_approve(entry_id: str | None, approve_all: bool) -> None:
    """Approve pending LLM-suggested gene pool entries."""

    async def _run() -> None:
        from src.db.engine import close_db, get_session
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
        from src.db.engine import close_db, get_session
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
        from src.db.engine import close_db, get_session
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

        click.echo("\nRun 'adagent approve yes --id <UUID>' to approve.")

        await close_db()

    asyncio.run(_run())


@approve.command("yes")
@click.option("--id", "approval_id", default=None, type=str, help="Approval queue item UUID.")
@click.option(
    "--all", "approve_all", is_flag=True, default=False, help="Approve all pending variants."
)
@click.option(
    "--deploy-now", is_flag=True, default=False, help="Deploy approved variants immediately."
)
@click.option("--campaign-id", default=None, type=str, help="Campaign UUID (required with --all).")
def approve_yes(
    approval_id: str | None, approve_all: bool, deploy_now: bool, campaign_id: str | None
) -> None:
    """Approve pending variant(s) for deployment."""

    async def _run() -> None:
        from src.db.engine import close_db, get_session
        from src.db.queries import approve_variant as approve_variant_q
        from src.db.queries import get_pending_approvals

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
                    __import__("sqlalchemy")
                    .select(__import__("src.db.tables", fromlist=["Campaign"]).Campaign)
                    .where(
                        __import__("src.db.tables", fromlist=["Campaign"]).Campaign.id
                        == deploy_campaign_id
                    )
                )
                campaign = campaign_row.scalar_one_or_none()
                if campaign:
                    if campaign.platform.value == "meta":
                        from src.adapters.meta_factory import (
                            get_meta_adapter_for_campaign,
                        )
                        from src.exceptions import (
                            MetaConnectionMissing,
                            MetaTokenExpired,
                        )

                        try:
                            adapter = await get_meta_adapter_for_campaign(
                                session, deploy_campaign_id
                            )
                        except (MetaConnectionMissing, MetaTokenExpired) as exc:
                            click.echo(f"Error: {exc}")
                            await close_db()
                            return
                    else:
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
        from src.db.engine import close_db, get_session
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


@cli.command("grant-access")
@click.option("--email", required=True, help="User email address.")
@click.option(
    "--campaign-id",
    required=True,
    help="Campaign UUID to grant the user access to.",
)
def grant_access(email: str, campaign_id: str) -> None:
    """Provision dashboard access for a user.

    Creates the user row if it doesn't exist (idempotent) and inserts a
    ``user_campaigns`` entry so the user can see the given campaign in
    the dashboard API.

    Example::

        python -m src.main grant-access --email me@company.com --campaign-id <uuid>
    """

    async def _run() -> None:
        from src.db.engine import close_db, get_session, init_db
        from src.db.queries import (
            create_user,
            get_campaign,
            get_user_by_email,
            grant_user_campaign_access,
        )

        try:
            campaign_uuid = UUID(campaign_id)
        except ValueError:
            click.echo(f"Error: {campaign_id!r} is not a valid UUID.")
            return

        await init_db()
        try:
            async with get_session() as session:
                campaign = await get_campaign(session, campaign_uuid)
                if campaign is None:
                    click.echo(f"Error: Campaign {campaign_id} not found.")
                    return

                user = await get_user_by_email(session, email)
                if user is None:
                    user = await create_user(session, email)
                    click.echo(f"Created user {user.email} ({user.id}).")
                else:
                    click.echo(f"Found existing user {user.email} ({user.id}).")

                await grant_user_campaign_access(
                    session, user_id=user.id, campaign_id=campaign_uuid
                )
                click.echo(f"Granted {user.email} access to campaign {campaign.name!r}.")
        finally:
            await close_db()

    asyncio.run(_run())


@cli.command(name="send-magic-link")
@click.option("--email", required=True, help="Recipient email address.")
def send_magic_link_cmd(email: str) -> None:
    """Generate and send a magic-link sign-in email.

    Creates a signed magic-link token and delivers it via SendGrid
    (or logs it to stdout in dev mode). The recipient is auto-provisioned
    as a user on first sign-in.

    Example::

        python -m src.main send-magic-link --email admin@example.com
    """

    async def _run() -> None:
        from src.dashboard.auth import create_magic_link_token
        from src.reports.auth_email import send_magic_link

        settings = get_settings()
        token = create_magic_link_token(email)
        link = f"{settings.api_base_url.rstrip('/')}/api/auth/verify?token={token}"

        click.echo(f"Sending magic link to {email}...")
        ok = await send_magic_link(email, link)
        if ok:
            click.echo("Magic link sent successfully.")
        else:
            click.echo("Failed to send magic link — check logs for details.")

    asyncio.run(_run())


@cli.command(name="send-daily-reports")
@click.option(
    "--report-date",
    default=None,
    type=str,
    help="Date to report on (YYYY-MM-DD). Defaults to yesterday.",
)
@click.option(
    "--dry-run",
    is_flag=True,
    default=False,
    help="List campaigns + owners without rendering or sending email.",
)
def send_daily_reports(report_date: str | None, dry_run: bool) -> None:
    """Phase H: send a daily report to every user-owned campaign's owner.

    Fans out across every active, user-owned campaign and renders a
    per-campaign daily report that's emailed to the owner's address
    (``users.email``) rather than the pre-Phase-H hardcoded
    ``settings.report_email_to`` inbox. Per-campaign errors are
    caught so one user's SendGrid failure can't block the batch.

    Intended to be called by the daily cron right after
    ``run-all-user-campaigns`` so fresh metrics land in inboxes.
    """

    async def _run() -> None:
        from datetime import date, timedelta

        from sqlalchemy import select

        from src.db.engine import close_db, get_session, init_db
        from src.db.tables import Campaign, User
        from src.services.reports import build_daily_report

        settings = get_settings()
        await init_db()

        if report_date:
            report_day = date.fromisoformat(report_date)
        else:
            report_day = date.today() - timedelta(days=1)

        async with get_session() as session:
            stmt = (
                select(Campaign, User.email)
                .join(User, User.id == Campaign.owner_user_id)
                .where(
                    Campaign.is_active.is_(True),
                    Campaign.owner_user_id.is_not(None),
                )
                .order_by(Campaign.name)
            )
            rows = (await session.execute(stmt)).all()

        if not rows:
            click.echo("No user-owned active campaigns found.")
            await close_db()
            return

        click.echo(f"Sending daily reports for {report_day.isoformat()} to {len(rows)} owner(s):")
        for campaign, email in rows:
            click.echo(f"  - {campaign.name} → {email}")

        if dry_run:
            click.echo("Dry run — no emails sent.")
            await close_db()
            return

        if not settings.sendgrid_api_key or settings.sendgrid_api_key.startswith("placeholder"):
            click.echo("Error: SENDGRID_API_KEY not configured in .env")
            await close_db()
            return

        from src.adapters.meta_factory import get_meta_adapter_for_campaign
        from src.reports.email import EmailReporter
        from src.services.ad_sync import sync_campaign_ads
        from src.services.poller import MetricsPoller

        sent = 0
        failed: list[tuple[str, str]] = []
        for campaign, owner_email in rows:
            try:
                # Step 0: sync any ads the user created directly in Meta
                # Ads Manager (outside Kleiber) into our deployments
                # table. Without this, the poller below only sees ads
                # that existed at initial ``import_campaign`` time, so
                # spend/purchase numbers miss everything Meta launched
                # without us knowing.
                try:
                    async with get_session() as session:
                        fresh = await session.get(Campaign, campaign.id)
                        if fresh is not None:
                            n = await sync_campaign_ads(session, fresh)
                            if n:
                                click.echo(
                                    f"  + {campaign.name}: discovered {n} "
                                    "new ad(s) from Meta"
                                )
                            await session.commit()
                except Exception as sync_exc:  # noqa: BLE001
                    # Sync failure shouldn't block the poll — known
                    # deployments still report; we just warn.
                    click.echo(
                        f"  ! {campaign.name}: ad sync failed "
                        f"({sync_exc}); continuing with known deployments"
                    )

                # Step 1: re-poll settled metrics for ``report_day`` so the
                # aggregate sees yesterday's *final* numbers. Without this,
                # the report only reflects whatever partial-day snapshot the
                # live optimization cron happened to write during the day —
                # which is how ``public/daily/*.html`` ended up with $0 spend
                # cards even though Meta had real spend for that date.
                try:
                    async with get_session() as session:
                        adapter = await get_meta_adapter_for_campaign(session, campaign.id)
                        poller = MetricsPoller(adapter=adapter, session=session)
                        await poller.poll_campaign_for_date(campaign.id, report_day)
                        await session.commit()
                except Exception as poll_exc:  # noqa: BLE001
                    # Polling failure shouldn't block the email — we still
                    # render from whatever's in the DB, just warn loudly.
                    click.echo(
                        f"  ! {campaign.name}: settled-metrics backfill failed "
                        f"({poll_exc}); rendering from existing data"
                    )

                async with get_session() as session:
                    report = await build_daily_report(session, campaign.id, report_day)
                reporter = EmailReporter(
                    api_key=settings.sendgrid_api_key,
                    from_email=settings.report_email_from,
                    to_email=owner_email,
                )
                ok = await reporter.send_daily_report(
                    report,
                    base_url=settings.report_base_url,
                    dashboard_url=(
                        f"{settings.frontend_base_url.rstrip('/')}"
                        f"/campaigns/{campaign.id}/reports/daily/"
                        f"{report_day.isoformat()}"
                    ),
                )
                if ok:
                    sent += 1
                    click.echo(f"  ✓ {campaign.name} → {owner_email}")
                else:
                    failed.append((str(campaign.id), "sendgrid returned non-2xx"))
                    click.echo(f"  ✗ {campaign.name} → {owner_email}: sendgrid failed")
            except Exception as exc:  # noqa: BLE001 — isolate per-campaign failures
                failed.append((str(campaign.id), str(exc)))
                click.echo(f"  ✗ {campaign.name} → {owner_email}: {exc}")

        click.echo(f"\nSummary: {sent}/{len(rows)} daily reports sent, {len(failed)} failed.")
        if failed:
            for cid, err in failed:
                click.echo(f"  {cid}: {err[:200]}")

        await close_db()

    asyncio.run(_run())


@cli.command(name="send-weekly-reports")
@click.option(
    "--week-start",
    default=None,
    type=str,
    help="Monday of the target week (YYYY-MM-DD). Defaults to last full week.",
)
@click.option(
    "--dry-run",
    is_flag=True,
    default=False,
    help="List campaigns + owners without rendering or sending email.",
)
def send_weekly_reports(week_start: str | None, dry_run: bool) -> None:
    """Phase H: send a weekly report to every user-owned campaign's owner.

    Mirrors :func:`send_daily_reports` but for the weekly digest. Runs
    :func:`src.services.weekly.run_weekly_generation` first so each
    campaign gets a fresh batch of proposed variants before its owner
    receives the email. Per-campaign errors are isolated.
    """

    async def _run() -> None:
        from datetime import date

        from sqlalchemy import select
        from sqlalchemy import text as sa_text

        from src.dashboard.tokens import create_review_token
        from src.db.engine import close_db, get_session, init_db
        from src.db.tables import Campaign, User
        from src.services.reports import build_weekly_report, default_last_full_week
        from src.services.weekly import run_weekly_generation

        settings = get_settings()
        await init_db()

        if week_start:
            ws = date.fromisoformat(week_start)
            from datetime import timedelta as _td

            we = ws + _td(days=6)
        else:
            ws, we = default_last_full_week()

        async with get_session() as session:
            stmt = (
                select(Campaign, User.email)
                .join(User, User.id == Campaign.owner_user_id)
                .where(
                    Campaign.is_active.is_(True),
                    Campaign.owner_user_id.is_not(None),
                )
                .order_by(Campaign.name)
            )
            rows = (await session.execute(stmt)).all()

        if not rows:
            click.echo("No user-owned active campaigns found.")
            await close_db()
            return

        click.echo(
            f"Sending weekly reports for {ws.isoformat()} – {we.isoformat()} "
            f"to {len(rows)} owner(s):"
        )
        for campaign, email in rows:
            click.echo(f"  - {campaign.name} → {email}")

        if dry_run:
            click.echo("Dry run — no generation, no emails sent.")
            await close_db()
            return

        if not settings.sendgrid_api_key or settings.sendgrid_api_key.startswith("placeholder"):
            click.echo("Error: SENDGRID_API_KEY not configured in .env")
            await close_db()
            return

        from src.reports.email import EmailReporter

        sent = 0
        failed: list[tuple[str, str]] = []
        for campaign, owner_email in rows:
            try:
                async with get_session() as session:
                    # Run generation pass so this week's proposals
                    # land in the email. Swallow generation errors —
                    # the report can still go out without new proposals.
                    expired_count = 0
                    generation_paused = False
                    try:
                        expired_count, generation_paused = await run_weekly_generation(
                            session, campaign.id
                        )
                    except Exception as exc:  # noqa: BLE001
                        click.echo(f"    warning: generation failed for {campaign.name}: {exc}")

                    pending_row = await session.execute(
                        sa_text(
                            "SELECT COUNT(*) FROM approval_queue "
                            "WHERE campaign_id = :id AND approved IS NULL "
                            "AND reviewed_at IS NULL"
                        ),
                        {"id": str(campaign.id)},
                    )
                    pending_count = int(pending_row.scalar_one() or 0)
                    review_url = (
                        f"{settings.report_base_url.rstrip('/')}/review/"
                        f"{create_review_token(campaign.id)}"
                        if pending_count > 0
                        else None
                    )

                    report = await build_weekly_report(
                        session,
                        campaign.id,
                        ws,
                        week_end=we,
                        expired_count=expired_count,
                        generation_paused=generation_paused,
                        review_url=review_url,
                    )
                    await session.commit()

                week_label = f"{ws.isocalendar()[0]}-W{ws.isocalendar()[1]:02d}"
                reporter = EmailReporter(
                    api_key=settings.sendgrid_api_key,
                    from_email=settings.report_email_from,
                    to_email=owner_email,
                )
                ok = await reporter.send_weekly_report_v2(
                    report,
                    campaign_name=report.campaign_name,
                    week_label=week_label,
                    base_url=settings.report_base_url,
                    review_url=report.review_url,
                    dashboard_url=(
                        f"{settings.frontend_base_url.rstrip('/')}"
                        f"/campaigns/{campaign.id}/reports/weekly/"
                        f"{ws.isoformat()}"
                    ),
                )
                if ok:
                    sent += 1
                    click.echo(f"  ✓ {campaign.name} → {owner_email}")
                else:
                    failed.append((str(campaign.id), "sendgrid returned non-2xx"))
                    click.echo(f"  ✗ {campaign.name} → {owner_email}: sendgrid failed")
            except Exception as exc:  # noqa: BLE001
                failed.append((str(campaign.id), str(exc)))
                click.echo(f"  ✗ {campaign.name} → {owner_email}: {exc}")

        click.echo(f"\nSummary: {sent}/{len(rows)} weekly reports sent, {len(failed)} failed.")
        if failed:
            for cid, err in failed:
                click.echo(f"  {cid}: {err[:200]}")

        await close_db()

    asyncio.run(_run())


@cli.command(name="send-approval-digests")
@click.option(
    "--dry-run",
    is_flag=True,
    default=False,
    help="Print the digest payload per owner without sending email.",
)
def send_approval_digests(dry_run: bool) -> None:
    """Phase H: nudge each owner about their pending approvals.

    Runs daily (regardless of whether a cycle fired) to prevent a
    silent failure mode where stale proposals sit unreviewed. One
    digest email per user with >0 pending rows, counting by
    ``action_type`` so the user knows *what kind* of review is
    waiting.

    Query is one grouped JOIN against
    ``approval_queue × campaigns × users`` with ``approved IS NULL``
    — sorted/capped client-side so we stay under SendGrid payload
    limits even for users with dozens of outstanding items.
    """

    async def _run() -> None:
        from sqlalchemy import text as sa_text

        from src.db.engine import close_db, get_session, init_db

        settings = get_settings()
        await init_db()

        async with get_session() as session:
            rows = await session.execute(
                sa_text(
                    """
                    SELECT c.owner_user_id,
                           u.email,
                           aq.action_type::text AS action_type,
                           COUNT(*) AS cnt
                    FROM approval_queue aq
                    JOIN campaigns c ON c.id = aq.campaign_id
                    JOIN users u ON u.id = c.owner_user_id
                    WHERE aq.approved IS NULL
                      AND aq.reviewed_at IS NULL
                    GROUP BY c.owner_user_id, u.email, aq.action_type
                    ORDER BY u.email, aq.action_type
                    """
                )
            )
            per_user: dict[str, dict[str, object]] = {}
            for owner_id, email, action_type, cnt in rows.fetchall():
                entry = per_user.setdefault(
                    str(owner_id),
                    {"email": email, "by_action_type": {}, "total": 0},
                )
                by_action = entry["by_action_type"]
                assert isinstance(by_action, dict)
                by_action[str(action_type)] = int(cnt)
                entry["total"] = int(entry["total"]) + int(cnt)  # type: ignore[arg-type]

        if not per_user:
            click.echo("No owners have pending approvals. Nothing to send.")
            await close_db()
            return

        click.echo(f"{len(per_user)} owner(s) have pending approvals:")
        for _, entry in per_user.items():
            by_action = entry["by_action_type"]
            assert isinstance(by_action, dict)
            parts = ", ".join(f"{k}={v}" for k, v in by_action.items())
            click.echo(f"  - {entry['email']}: {entry['total']} pending ({parts})")

        if dry_run:
            click.echo("Dry run — no emails sent.")
            await close_db()
            return

        if not settings.sendgrid_api_key or settings.sendgrid_api_key.startswith("placeholder"):
            click.echo("Error: SENDGRID_API_KEY not configured in .env")
            await close_db()
            return

        import httpx

        review_url = f"{settings.frontend_base_url.rstrip('/')}/experiments"

        sent = 0
        failed: list[tuple[str, str]] = []
        async with httpx.AsyncClient(timeout=30.0) as client:
            for _, entry in per_user.items():
                owner_email = str(entry["email"])
                by_action = entry["by_action_type"]
                assert isinstance(by_action, dict)
                total = int(entry["total"])  # type: ignore[arg-type]

                # One line per action_type category — deliberately
                # compact (see Phase H red flag #7: digests must not
                # enumerate each pending row for users 30+ behind).
                lines = [
                    "<p>You have pending ad optimization proposals waiting for your review.</p>",
                    "<ul>",
                ]
                human_labels = {
                    "new_variant": "new variant(s) to launch",
                    "pause_variant": "ad(s) to pause",
                    "scale_budget": "budget change(s) to confirm",
                    "promote_winner": "winner(s) to promote",
                }
                for action, cnt in by_action.items():
                    label = human_labels.get(action, action)
                    lines.append(f"<li><b>{cnt}</b> {label}</li>")
                lines.append("</ul>")
                lines.append(f'<p><a href="{review_url}">Review in dashboard →</a></p>')
                html = "".join(lines)

                subject = (
                    f"[Ad Agent] {total} pending approval"
                    f"{'' if total == 1 else 's'} awaiting your review"
                )
                payload: dict[str, object] = {
                    "personalizations": [
                        {
                            "to": [{"email": owner_email}],
                            "subject": subject,
                        }
                    ],
                    "from": {"email": settings.report_email_from},
                    "content": [{"type": "text/html", "value": html}],
                }
                headers = {
                    "Authorization": f"Bearer {settings.sendgrid_api_key}",
                    "Content-Type": "application/json",
                }

                try:
                    resp = await client.post(
                        "https://api.sendgrid.com/v3/mail/send",
                        json=payload,
                        headers=headers,
                    )
                    if resp.status_code in (200, 202):
                        sent += 1
                        click.echo(f"  ✓ {owner_email}")
                    else:
                        failed.append((owner_email, f"HTTP {resp.status_code}"))
                        click.echo(f"  ✗ {owner_email}: HTTP {resp.status_code} {resp.text[:200]}")
                except Exception as exc:  # noqa: BLE001
                    failed.append((owner_email, str(exc)))
                    click.echo(f"  ✗ {owner_email}: {exc}")

        click.echo(f"\nSummary: {sent}/{len(per_user)} digests sent, {len(failed)} failed.")

        await close_db()

    asyncio.run(_run())


def main() -> None:
    """Package entry point."""
    cli()


if __name__ == "__main__":
    main()
