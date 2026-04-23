"""Main optimization cycle coordinator.

Runs the full monitor -> analyze -> act -> generate -> deploy -> report
pipeline. Each step is wrapped in try/except so one failure does not
stop the entire cycle. All actions are logged to test_cycles and
cycle_actions for auditing.
"""

from __future__ import annotations

import json
import logging
import traceback
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import anthropic
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.adapters.base import BaseAdapter
from src.agents.generator import GeneratorAgent
from src.config import Settings
from src.db.queries import (
    get_campaign_owner_id,
    get_element_rankings,
    get_top_interactions,
    queue_pause_proposal,
    queue_scale_proposal,
    upsert_element_interaction,
    upsert_element_performance,
)
from src.exceptions import CycleError, LLMError
from src.models.analysis import ElementInsight, InteractionInsight
from src.models.genome import GenePool
from src.services.allocation import allocate_budgets
from src.services.fatigue import detect_fatigue
from src.services.interactions import compute_interactions
from src.services.poller import MetricsPoller, MetricsSnapshot
from src.services.stats import compare_variants, element_significance, has_sufficient_data
from src.services.usage import AgentContext

logger = logging.getLogger(__name__)


# Minimum gap between consecutive scale_budget proposals per campaign.
# Thompson sampling is a single Beta draw per variant per cycle — at
# the target user's $5–100/day budgets each variant gets only a few
# hundred impressions a day, so a fresh draw every 24 hours is
# dominated by sampling noise rather than underlying CTR signal. A
# weekly cadence lets the Beta posteriors actually tighten between
# draws. Applies campaign-wide (not per-variant) because Thompson
# re-splits the full budget set — it doesn't make sense to queue a
# new split for variant A while the prior split for B is still
# pending.
#
# pause_variant and promote_winner paths deliberately stay daily —
# they're already gated on ``campaigns.min_impressions_for_significance``
# (default 1000) + ``campaigns.confidence_threshold`` (default 95%),
# so they only fire on statistically meaningful outliers. Audience
# fatigue also stays daily (a 3-day decline is a daily-cadence
# signal by definition).
SCALE_BUDGET_COOLDOWN: timedelta = timedelta(days=7)


@dataclass
class CycleAction:
    """A single action taken during a cycle, for audit logging."""

    variant_id: uuid.UUID | None
    action: str  # matches action_type enum: launch, pause, increase_budget, etc.
    details: dict[str, str | int | float | bool | None]


@dataclass
class CycleReport:
    """Summary of a completed optimization cycle."""

    cycle_id: uuid.UUID
    campaign_id: uuid.UUID
    cycle_number: int
    phase_reached: str = "monitor"
    snapshots_collected: int = 0
    variants_launched: int = 0
    variants_paused: int = 0
    variants_promoted: int = 0
    actions: list[CycleAction] = field(default_factory=list)
    errors: dict[str, str] = field(default_factory=dict)
    summary_text: str = ""


class Orchestrator:
    """Coordinates a single optimization cycle for a campaign.

    Args:
        adapter: The ad platform adapter for deploying/pausing ads.
        session_factory: Async session factory for database access.
        settings: Application settings.
    """

    def __init__(
        self,
        adapter: BaseAdapter,
        session_factory: async_sessionmaker[AsyncSession],
        settings: Settings,
        auto_deploy: bool = False,
    ) -> None:
        self._adapter = adapter
        self._session_factory = session_factory
        self._settings = settings
        self._auto_deploy = auto_deploy

    async def run_cycle(
        self,
        campaign_id: uuid.UUID,
        skip_generate: bool = False,
    ) -> CycleReport:
        """Execute a full optimization cycle for the given campaign.

        Phases: monitor -> analyze -> act -> generate -> deploy -> report.
        Each phase is isolated — a failure in one phase is logged and the
        cycle continues to subsequent phases where possible.

        If *skip_generate* is True, phases 4 (generate) and 5 (deploy)
        are skipped — useful for metrics-only cycles.
        """
        async with self._session_factory() as session:
            cycle_number = await self._next_cycle_number(session, campaign_id)
            cycle_id = uuid.uuid4()

            # Phase E: resolve the owning user once per cycle so the
            # generator + any downstream agents can log usage under
            # the right (user, campaign, cycle) triple. Legacy
            # campaigns without an owner still run — they'll just
            # log with user_id = NULL.
            try:
                owner_user_id = await get_campaign_owner_id(session, campaign_id)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Couldn't resolve owner for campaign %s: %s", campaign_id, exc)
                owner_user_id = None
            self._current_usage_ctx = AgentContext(
                user_id=owner_user_id,
                campaign_id=campaign_id,
                cycle_id=cycle_id,
            )
            self._current_usage_session = session

            # Create the test_cycles record
            await session.execute(
                text("""
                    INSERT INTO test_cycles (id, campaign_id, cycle_number, phase, started_at)
                    VALUES (:id, :campaign_id, :cycle_number, 'monitor', :started_at)
                """),
                {
                    "id": cycle_id,
                    "campaign_id": campaign_id,
                    "cycle_number": cycle_number,
                    "started_at": datetime.now(UTC),
                },
            )
            await session.flush()

            report = CycleReport(
                cycle_id=cycle_id,
                campaign_id=campaign_id,
                cycle_number=cycle_number,
            )

            # Each phase runs in a savepoint so a failure in one phase
            # does not poison the transaction for subsequent phases.

            # --- Phase 1: Monitor ---
            snapshots: list[MetricsSnapshot] = []
            try:
                async with session.begin_nested():
                    snapshots = await self._phase_monitor(session, campaign_id)
                    report.snapshots_collected = len(snapshots)
                    report.phase_reached = "monitor"
                    await self._update_cycle_phase(session, cycle_id, "monitor")
            except Exception as exc:
                report.errors["monitor"] = _format_error(exc)
                logger.error(
                    "Cycle %d monitor failed for campaign %s: %s",
                    cycle_number,
                    campaign_id,
                    exc,
                    exc_info=True,
                )

            # --- Phase 2: Analyze ---
            variant_data: list[_VariantData] = []
            try:
                async with session.begin_nested():
                    variant_data = await self._phase_analyze(session, campaign_id)
                    await self._persist_element_data(session, campaign_id, variant_data)
                    report.phase_reached = "analyze"
                    await self._update_cycle_phase(session, cycle_id, "analyze")
            except Exception as exc:
                report.errors["analyze"] = _format_error(exc)
                logger.error(
                    "Cycle %d analyze failed for campaign %s: %s",
                    cycle_number,
                    campaign_id,
                    exc,
                    exc_info=True,
                )

            # --- Phase 3: Act (pause losers, scale winners) ---
            try:
                async with session.begin_nested():
                    actions = await self._phase_act(session, campaign_id, variant_data)
                    report.actions.extend(actions)
                    report.variants_paused = sum(1 for a in actions if a.action == "pause")
                    report.variants_promoted = sum(
                        1 for a in actions if a.action == "promote_winner"
                    )
                    report.phase_reached = "analyze"
            except Exception as exc:
                report.errors["act"] = _format_error(exc)
                logger.error(
                    "Cycle %d act failed for campaign %s: %s",
                    cycle_number,
                    campaign_id,
                    exc,
                    exc_info=True,
                )

            # --- Phase 4: Generate ---
            new_genomes: list[_NewGenome] = []
            if skip_generate:
                logger.info("Skipping generate/deploy phases (--no-generate)")
            else:
                try:
                    async with session.begin_nested():
                        new_genomes = await self._phase_generate(session, campaign_id, variant_data)
                        report.phase_reached = "generate"
                        await self._update_cycle_phase(session, cycle_id, "generate")
                except Exception as exc:
                    report.errors["generate"] = _format_error(exc)
                    logger.error(
                        "Cycle %d generate failed for campaign %s: %s",
                        cycle_number,
                        campaign_id,
                        exc,
                        exc_info=True,
                    )

                # --- Phase 5: Deploy ---
                try:
                    async with session.begin_nested():
                        deploy_actions = await self._phase_deploy(session, campaign_id, new_genomes)
                        report.actions.extend(deploy_actions)
                        report.variants_launched = len(deploy_actions)
                        report.phase_reached = "deploy"
                        await self._update_cycle_phase(session, cycle_id, "deploy")
                except Exception as exc:
                    report.errors["deploy"] = _format_error(exc)
                    logger.error(
                        "Cycle %d deploy failed for campaign %s: %s",
                        cycle_number,
                        campaign_id,
                        exc,
                        exc_info=True,
                    )

            # --- Phase 6: Report ---
            try:
                async with session.begin_nested():
                    report.phase_reached = "report"
                    report.summary_text = self._build_summary(report)
                    await self._update_cycle_phase(session, cycle_id, "complete")
            except Exception as exc:
                report.errors["report"] = _format_error(exc)
                logger.error(
                    "Cycle %d report failed for campaign %s: %s",
                    cycle_number,
                    campaign_id,
                    exc,
                    exc_info=True,
                )

            # Persist all cycle actions and finalize
            async with session.begin_nested():
                for action in report.actions:
                    await self._log_action(session, cycle_id, action)
                await self._finalize_cycle(session, cycle_id, report)

            await session.commit()

        return report

    # ------------------------------------------------------------------
    # Phase implementations
    # ------------------------------------------------------------------

    async def _phase_monitor(
        self, session: AsyncSession, campaign_id: uuid.UUID
    ) -> list[MetricsSnapshot]:
        """Poll metrics from all active deployments."""
        poller = MetricsPoller(adapter=self._adapter, session=session)
        return await poller.poll_campaign(campaign_id)

    async def _phase_analyze(
        self, session: AsyncSession, campaign_id: uuid.UUID
    ) -> list[_VariantData]:
        """Fetch variant metrics and run significance tests against the baseline."""
        rows = await session.execute(
            text("""
                SELECT v.id, v.variant_code, v.status, v.genome,
                       COALESCE(m.impressions, 0) AS impressions,
                       COALESCE(m.clicks, 0) AS clicks,
                       COALESCE(m.conversions, 0) AS conversions,
                       COALESCE(m.spend, 0) AS spend
                FROM variants v
                LEFT JOIN LATERAL (
                    SELECT impressions, clicks, conversions, spend
                    FROM metrics
                    WHERE variant_id = v.id
                    ORDER BY recorded_at DESC
                    LIMIT 1
                ) m ON TRUE
                WHERE v.campaign_id = :campaign_id
                  AND v.status = 'active'
                ORDER BY v.variant_code
            """),
            {"campaign_id": campaign_id},
        )

        data: list[_VariantData] = []
        for row in rows.fetchall():
            data.append(
                _VariantData(
                    variant_id=row[0],
                    variant_code=row[1],
                    status=row[2],
                    genome=row[3] if isinstance(row[3], dict) else {},
                    impressions=int(row[4]),
                    clicks=int(row[5]),
                    conversions=int(row[6]),
                    spend=float(row[7]),
                )
            )

        return data

    async def _persist_element_data(
        self,
        session: AsyncSession,
        campaign_id: uuid.UUID,
        variant_data: list[_VariantData],
    ) -> None:
        """Compute and persist element performance and interaction data."""
        if not variant_data:
            return

        # --- Element performance ---
        # Group CTRs by (slot_name, slot_value)
        from collections import defaultdict

        element_ctrs: dict[tuple[str, str], list[tuple[float, int, int]]] = defaultdict(list)
        all_ctrs: list[float] = []

        for v in variant_data:
            if v.impressions == 0:
                continue
            ctr = v.clicks / v.impressions
            all_ctrs.append(ctr)
            for slot_name, slot_value in v.genome.items():
                element_ctrs[(slot_name, slot_value)].append((ctr, v.impressions, v.conversions))

        global_mean_ctr = sum(all_ctrs) / len(all_ctrs) if all_ctrs else 0.0

        for (slot_name, slot_value), entries in element_ctrs.items():
            ctrs = [c for c, _, _ in entries]
            total_imps = sum(i for _, i, _ in entries)
            total_conv = sum(c for _, _, c in entries)
            weighted_avg = sum(c * i for c, i, _ in entries) / total_imps if total_imps > 0 else 0.0

            _, _, confidence = element_significance(
                element_ctrs=ctrs, global_mean_ctr=global_mean_ctr
            )

            await upsert_element_performance(
                session,
                campaign_id=campaign_id,
                slot_name=slot_name,
                slot_value=slot_value,
                stats={
                    "variants_tested": len(entries),
                    "avg_ctr": round(weighted_avg, 6),
                    "avg_cpa": None,
                    "best_ctr": round(max(ctrs), 6) if ctrs else None,
                    "worst_ctr": round(min(ctrs), 6) if ctrs else None,
                    "total_impressions": total_imps,
                    "total_conversions": total_conv,
                    "confidence": round(confidence, 2),
                },
            )

        # --- Element interactions ---
        variants_with_metrics = [
            (v.genome, v.clicks / v.impressions) for v in variant_data if v.impressions > 0
        ]
        interactions = compute_interactions(variants_with_metrics, min_combined_variants=2)

        for ix in interactions[:50]:  # cap at top 50 to avoid excessive writes
            await upsert_element_interaction(
                session,
                campaign_id=campaign_id,
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
                    "confidence": None,
                },
            )

        await session.flush()
        logger.info(
            "Persisted element data: %d elements, %d interactions for campaign %s",
            len(element_ctrs),
            min(len(interactions), 50),
            campaign_id,
        )

    async def _phase_act(
        self,
        session: AsyncSession,
        campaign_id: uuid.UUID,
        variant_data: list[_VariantData],
    ) -> list[CycleAction]:
        """Propose pause/scale/promote actions — never mutate Meta directly.

        Phase H: this function used to call ``self._adapter.pause_ad``
        and ``self._adapter.update_budget`` inline. Those calls are
        gone. Every would-be mutation is now queued as a row in
        ``approval_queue`` and the user has to approve it from the
        ``/experiments`` page before the deployer service actually
        pushes anything to Meta. The only side-effects this function
        has are DB writes (approval_queue + cycle_actions audit log).

        Every propose-step also writes a ``queue_for_approval``
        cycle_action row via the returned ``CycleAction`` list so the
        audit trail shows "at 12:00 UTC the agent thought variant V7
        was a statistically significant loser and queued a pause
        proposal for human review". No mysterious Meta state changes
        without a trail.
        """
        actions: list[CycleAction] = []

        if len(variant_data) < 2:
            logger.info(
                "Fewer than 2 active variants for campaign %s, skipping act phase", campaign_id
            )
            return actions

        # Find the baseline (first variant or most impressions)
        baseline = max(variant_data, key=lambda v: v.impressions)

        # Fetch campaign settings
        campaign_row = await session.execute(
            text(
                "SELECT min_impressions_for_significance, confidence_threshold FROM campaigns WHERE id = :id"
            ),
            {"id": campaign_id},
        )
        campaign_settings = campaign_row.fetchone()
        min_impressions = (
            int(campaign_settings[0]) if campaign_settings else self._settings.min_impressions
        )
        confidence_threshold = (
            float(campaign_settings[1])
            if campaign_settings
            else self._settings.confidence_threshold
        )

        # Track which variants we've already queued a pause proposal for
        # so the fatigue branch doesn't stack a second proposal on top
        # of the stats branch in the same cycle. has_open_proposal()
        # would dedupe eventually but we'd rather not even insert.
        proposed_pauses: set[uuid.UUID] = set()

        # Run significance tests
        for variant in variant_data:
            if variant.variant_id == baseline.variant_id:
                continue

            if not has_sufficient_data(variant.impressions, min_impressions):
                continue

            z_score, p_value, is_significant = compare_variants(
                baseline_clicks=baseline.clicks,
                baseline_impressions=baseline.impressions,
                variant_clicks=variant.clicks,
                variant_impressions=variant.impressions,
                confidence_threshold=confidence_threshold,
            )

            variant_ctr = variant.clicks / variant.impressions if variant.impressions > 0 else 0
            baseline_ctr = baseline.clicks / baseline.impressions if baseline.impressions > 0 else 0

            if is_significant and variant_ctr > baseline_ctr:
                # Winner: this is a pure DB state flip (mark winner)
                # — promoting doesn't touch Meta on its own, so it's
                # safe to do inline. If we later add "pause losers
                # when a winner is promoted" as a side-effect, that
                # gets queued too.
                await session.execute(
                    text("UPDATE variants SET status = 'winner' WHERE id = :id"),
                    {"id": variant.variant_id},
                )
                actions.append(
                    CycleAction(
                        variant_id=variant.variant_id,
                        action="promote_winner",
                        details={
                            "z_score": round(z_score, 4),
                            "p_value": round(p_value, 6),
                            "variant_ctr": round(variant_ctr, 5),
                            "baseline_ctr": round(baseline_ctr, 5),
                        },
                    )
                )
            elif is_significant and variant_ctr < baseline_ctr:
                # Significant loser: queue a pause proposal (NOT an
                # immediate pause). The user must approve from the
                # dashboard before the deployer actually hits Meta.
                evidence = {
                    "reason": "statistically_significant_loser",
                    "z_score": round(z_score, 4),
                    "p_value": round(p_value, 6),
                    "variant_ctr": round(variant_ctr, 5),
                    "baseline_ctr": round(baseline_ctr, 5),
                    "impressions": variant.impressions,
                    "clicks": variant.clicks,
                }
                proposal_id = await self._queue_pause_for_variant(
                    session,
                    campaign_id=campaign_id,
                    variant=variant,
                    reason="statistically_significant_loser",
                    evidence=evidence,
                )
                if proposal_id is not None:
                    proposed_pauses.add(variant.variant_id)
                    actions.append(
                        CycleAction(
                            variant_id=variant.variant_id,
                            action="queue_for_approval",
                            details={
                                "proposal_id": str(proposal_id),
                                "action_type": "pause_variant",
                                **evidence,
                            },
                        )
                    )

            # Check for fatigue on variants with enough data — but only
            # if we haven't already queued a pause proposal for this
            # variant in the stats branch above.
            if (
                has_sufficient_data(variant.impressions, min_impressions)
                and variant.variant_id not in proposed_pauses
            ):
                daily_ctrs = await self._get_daily_ctrs(session, variant.variant_id)
                fatigue_result = detect_fatigue(daily_ctrs)
                if fatigue_result.is_fatigued:
                    evidence = {
                        "reason": "audience_fatigue",
                        "consecutive_decline_days": fatigue_result.consecutive_decline_days,
                        "trend_slope": round(fatigue_result.trend_slope, 6),
                    }
                    proposal_id = await self._queue_pause_for_variant(
                        session,
                        campaign_id=campaign_id,
                        variant=variant,
                        reason="audience_fatigue",
                        evidence=evidence,
                    )
                    if proposal_id is not None:
                        proposed_pauses.add(variant.variant_id)
                        actions.append(
                            CycleAction(
                                variant_id=variant.variant_id,
                                action="queue_for_approval",
                                details={
                                    "proposal_id": str(proposal_id),
                                    "action_type": "pause_variant",
                                    **evidence,
                                },
                            )
                        )

        # Thompson sampling budget reallocation — propose-only AND
        # rate-limited to at most once per ``SCALE_BUDGET_COOLDOWN``
        # (7 days). Skip the block entirely when the most recent
        # scale_budget proposal for this campaign (pending, approved,
        # or declined) was submitted within the cooldown window.
        #
        # See ``SCALE_BUDGET_COOLDOWN`` at the top of the module for
        # the full rationale; short version is that Thompson's single
        # Beta draw per variant per cycle is dominated by sampling
        # noise at small-advertiser budgets, and letting a week of
        # fresh impressions accumulate between draws is the cleanest
        # way to keep the queue signal-to-noise high.
        still_active = [v for v in variant_data if v.variant_id not in proposed_pauses]

        recent_scale = await session.execute(
            text(
                """
                SELECT MAX(submitted_at)
                FROM approval_queue
                WHERE campaign_id = :id
                  AND action_type = 'scale_budget'
                """
            ),
            {"id": campaign_id},
        )
        last_scale_at: datetime | None = recent_scale.scalar()
        scale_cooldown_active = (
            last_scale_at is not None
            and (datetime.now(UTC) - last_scale_at) < SCALE_BUDGET_COOLDOWN
        )
        if scale_cooldown_active:
            logger.info(
                "Skipping scale_budget proposals for campaign %s — last "
                "proposal at %s is within %d-day cooldown.",
                campaign_id,
                last_scale_at,
                SCALE_BUDGET_COOLDOWN.days,
            )

        if not scale_cooldown_active and len(still_active) >= 2:
            campaign_budget_row = await session.execute(
                text("SELECT daily_budget FROM campaigns WHERE id = :id"),
                {"id": campaign_id},
            )
            budget_row = campaign_budget_row.fetchone()
            if budget_row:
                total_budget = Decimal(str(budget_row[0]))
                thompson_input = [(v.variant_id, v.clicks, v.impressions) for v in still_active]
                allocations = allocate_budgets(thompson_input, total_budget)

                for variant_id, new_budget in allocations.items():
                    variant = next((v for v in still_active if v.variant_id == variant_id), None)
                    if variant is None:
                        continue

                    deployment_info = await self._get_deployment_for_variant(session, variant_id)
                    if deployment_info is None:
                        continue
                    deployment_id, platform_ad_id, current_budget = deployment_info

                    # Skip if the new budget is within 5% of the current
                    # — not worth pinging the user with a trivial change.
                    current = Decimal(str(current_budget))
                    delta = abs(new_budget - current)
                    if current > 0 and delta / current < Decimal("0.05"):
                        continue

                    evidence = {
                        "allocation_method": "thompson_sampling",
                        "impressions": variant.impressions,
                        "clicks": variant.clicks,
                    }
                    proposal_id = await queue_scale_proposal(
                        session,
                        campaign_id=campaign_id,
                        deployment_id=deployment_id,
                        platform_ad_id=platform_ad_id,
                        current_budget=current,
                        proposed_budget=new_budget,
                        evidence=evidence,
                        genome_snapshot=variant.genome,
                    )
                    if proposal_id is not None:
                        actions.append(
                            CycleAction(
                                variant_id=variant_id,
                                action="queue_for_approval",
                                details={
                                    "proposal_id": str(proposal_id),
                                    "action_type": "scale_budget",
                                    "current_budget": float(current),
                                    "proposed_budget": float(new_budget),
                                    **evidence,
                                },
                            )
                        )

        return actions

    async def _queue_pause_for_variant(
        self,
        session: AsyncSession,
        *,
        campaign_id: uuid.UUID,
        variant: _VariantData,
        reason: str,
        evidence: dict,
    ) -> uuid.UUID | None:
        """Look up the variant's live deployment and queue a pause proposal.

        Returns the new approval_queue row id, or ``None`` if the
        variant has no active deployment (shouldn't happen for an
        active variant but we'd rather skip cleanly than raise) or if
        an open pause proposal already exists (dedupe).
        """
        deployment_info = await self._get_deployment_for_variant(session, variant.variant_id)
        if deployment_info is None:
            logger.warning(
                "Variant %s has no active deployment; skipping pause proposal",
                variant.variant_id,
            )
            return None
        deployment_id, platform_ad_id, _ = deployment_info
        return await queue_pause_proposal(
            session,
            campaign_id=campaign_id,
            deployment_id=deployment_id,
            platform_ad_id=platform_ad_id,
            reason=reason,
            evidence=evidence,
            genome_snapshot=variant.genome,
        )

    async def _get_deployment_for_variant(
        self, session: AsyncSession, variant_id: uuid.UUID
    ) -> tuple[uuid.UUID, str, float] | None:
        """Return (deployment_id, platform_ad_id, daily_budget) for the variant's active deployment.

        Phase H replacement for ``_get_platform_ad_id`` — callers now
        want the deployment row id (so the approval payload can
        reference it) *and* the current budget (so scale proposals can
        record old → new). Returns ``None`` if the variant has no
        active deployment.
        """
        result = await session.execute(
            text(
                """
                SELECT id, platform_ad_id, daily_budget FROM deployments
                WHERE variant_id = :variant_id AND is_active = TRUE
                LIMIT 1
                """
            ),
            {"variant_id": variant_id},
        )
        row = result.fetchone()
        if row is None:
            return None
        return (row[0], str(row[1]), float(row[2] or 0))

    async def _phase_generate(
        self,
        session: AsyncSession,
        campaign_id: uuid.UUID,
        variant_data: list[_VariantData],
    ) -> list[_NewGenome]:
        """Generate new variant genomes using the LLM-powered GeneratorAgent.

        Consults element performance rankings and interaction data from the DB,
        passes them to the generator along with existing genomes.
        """
        # Check how many slots are available
        campaign_row = await session.execute(
            text("SELECT max_concurrent_variants FROM campaigns WHERE id = :id"),
            {"id": campaign_id},
        )
        row = campaign_row.fetchone()
        max_variants = int(row[0]) if row else self._settings.max_concurrent_variants

        active_count_row = await session.execute(
            text("SELECT COUNT(*) FROM variants WHERE campaign_id = :id AND status = 'active'"),
            {"id": campaign_id},
        )
        active_count = int(active_count_row.scalar_one())
        slots_available = max(0, max_variants - active_count)

        if slots_available == 0:
            logger.info(
                "No variant slots available for campaign %s (max=%d, active=%d)",
                campaign_id,
                max_variants,
                active_count,
            )
            return []

        max_new = min(slots_available, 3)  # generate up to 3 per cycle

        # Load gene pool from DB
        gene_pool = await self._load_gene_pool(session)

        # Get element rankings and top interactions from DB
        element_rankings = await get_element_rankings(session, campaign_id)
        top_interactions = await get_top_interactions(session, campaign_id)

        # Convert DB models to analysis Pydantic models for the generator
        element_insights = [
            ElementInsight(
                slot_name=ep.slot_name,
                slot_value=ep.slot_value,
                variants_tested=ep.variants_tested,
                avg_ctr=ep.avg_ctr or Decimal("0"),
                avg_cpa=ep.avg_cpa,
                best_ctr=ep.best_ctr,
                worst_ctr=ep.worst_ctr,
                total_impressions=ep.total_impressions,
                total_conversions=ep.total_conversions,
                confidence=ep.confidence,
            )
            for ep in element_rankings
        ]

        interaction_insights = [
            InteractionInsight(
                slot_a_name=ei.slot_a_name,
                slot_a_value=ei.slot_a_value,
                slot_b_name=ei.slot_b_name,
                slot_b_value=ei.slot_b_value,
                variants_tested=ei.variants_tested,
                combined_avg_ctr=ei.combined_avg_ctr or Decimal("0"),
                solo_a_avg_ctr=ei.solo_a_avg_ctr,
                solo_b_avg_ctr=ei.solo_b_avg_ctr,
                interaction_lift=ei.interaction_lift,
                confidence=ei.confidence,
            )
            for ei in top_interactions
        ]

        # Existing genomes for duplicate checking
        existing_genomes = [v.genome for v in variant_data]

        # Also include non-active variants to avoid re-generating retired ones
        all_genomes_row = await session.execute(
            text("SELECT genome FROM variants WHERE campaign_id = :id AND status != 'retired'"),
            {"id": campaign_id},
        )
        for row in all_genomes_row.fetchall():
            genome = row[0]
            if isinstance(genome, dict) and genome not in existing_genomes:
                existing_genomes.append(genome)

        # Call the generator agent. We pass the current cycle's
        # usage context + session so the generator can log its
        # LLM spend against the owning user. Both fall back to
        # ``None`` for callers that bypass ``run_cycle`` (and for
        # legacy campaigns without an owner resolved earlier).
        client = anthropic.AsyncAnthropic(api_key=self._settings.anthropic_api_key)
        generator = GeneratorAgent(
            client=client,
            model=self._settings.anthropic_model,
            usage_session=getattr(self, "_current_usage_session", None),
            usage_context=(
                AgentContext(
                    user_id=self._current_usage_ctx.user_id,
                    campaign_id=self._current_usage_ctx.campaign_id,
                    cycle_id=self._current_usage_ctx.cycle_id,
                    agent="generator",
                )
                if getattr(self, "_current_usage_ctx", None) is not None
                else None
            ),
        )

        try:
            results = await generator.generate_variants(
                gene_pool=gene_pool,
                element_rankings=element_insights,
                top_interactions=interaction_insights,
                current_variants=existing_genomes,
                max_new=max_new,
            )
        except LLMError as exc:
            logger.warning("Generator agent produced no valid variants: %s", exc)
            return []

        # Determine generation number (parent's generation + 1)
        max_gen_row = await session.execute(
            text("SELECT COALESCE(MAX(generation), 0) FROM variants WHERE campaign_id = :id"),
            {"id": campaign_id},
        )
        current_max_gen = int(max_gen_row.scalar_one())

        new_genomes: list[_NewGenome] = []
        for result in results:
            new_genomes.append(
                _NewGenome(
                    genome=result.genome,
                    hypothesis=result.hypothesis,
                    generation=current_max_gen + 1,
                )
            )

        logger.info(
            "Generated %d new variant genomes for campaign %s",
            len(new_genomes),
            campaign_id,
        )
        return new_genomes

    async def _phase_deploy(
        self,
        session: AsyncSession,
        campaign_id: uuid.UUID,
        new_genomes: list[_NewGenome],
    ) -> list[CycleAction]:
        """Create variant records and either deploy or queue for approval.

        When auto_deploy=True (legacy mode):
        1. Insert variant as 'active', call adapter.create_ad(), create deployment.

        When auto_deploy=False (default, approval gate):
        1. Insert variant as 'pending', add to approval_queue.
        2. Actual deployment happens later via deployer service.
        """
        if not new_genomes:
            return []

        actions: list[CycleAction] = []

        # Get campaign info
        campaign_row = await session.execute(
            text("""
                SELECT platform, platform_campaign_id, daily_budget
                FROM campaigns WHERE id = :id
            """),
            {"id": campaign_id},
        )
        campaign = campaign_row.fetchone()
        if not campaign:
            raise CycleError(phase="deploy", message=f"Campaign {campaign_id} not found")

        platform = str(campaign[0])
        platform_campaign_id = str(campaign[1]) if campaign[1] else ""

        for ng in new_genomes:
            try:
                # 1. Get next variant code
                code_row = await session.execute(
                    text("SELECT next_variant_code(:id)"),
                    {"id": campaign_id},
                )
                variant_code = str(code_row.scalar_one())

                # 2. Insert variant (pending or active depending on mode)
                variant_id = uuid.uuid4()
                initial_status = "active" if self._auto_deploy else "pending"
                await session.execute(
                    text("""
                        INSERT INTO variants (id, campaign_id, variant_code, genome, status,
                                             generation, hypothesis, created_at)
                        VALUES (:id, :campaign_id, :variant_code, :genome, :status,
                                :generation, :hypothesis, NOW())
                    """),
                    {
                        "id": variant_id,
                        "campaign_id": campaign_id,
                        "variant_code": variant_code,
                        "genome": json.dumps(ng.genome),
                        "status": initial_status,
                        "generation": ng.generation,
                        "hypothesis": ng.hypothesis,
                    },
                )

                if self._auto_deploy:
                    # Legacy: deploy immediately
                    action = await self._deploy_single_variant(
                        session,
                        campaign_id,
                        variant_id,
                        variant_code,
                        ng,
                        platform,
                        platform_campaign_id,
                    )
                    actions.append(action)
                else:
                    # Queue for human approval
                    await session.execute(
                        text("""
                            INSERT INTO approval_queue
                                (id, variant_id, campaign_id, genome_snapshot, hypothesis, submitted_at)
                            VALUES (:id, :variant_id, :campaign_id, :genome, :hypothesis, NOW())
                        """),
                        {
                            "id": uuid.uuid4(),
                            "variant_id": variant_id,
                            "campaign_id": campaign_id,
                            "genome": json.dumps(ng.genome),
                            "hypothesis": ng.hypothesis,
                        },
                    )

                    actions.append(
                        CycleAction(
                            variant_id=variant_id,
                            action="queue_for_approval",
                            details={
                                "variant_code": variant_code,
                                "hypothesis": ng.hypothesis,
                                "genome": ng.genome,
                            },
                        )
                    )

                    logger.info(
                        "Queued variant %s for approval (hypothesis: %s)",
                        variant_code,
                        ng.hypothesis,
                    )
            except Exception as exc:
                logger.warning(
                    "Failed to process variant for genome %s: %s",
                    ng.genome,
                    exc,
                )

        await session.flush()
        return actions

    # ------------------------------------------------------------------
    # Helper methods
    # ------------------------------------------------------------------

    async def _deploy_single_variant(
        self,
        session: AsyncSession,
        campaign_id: uuid.UUID,
        variant_id: uuid.UUID,
        variant_code: str,
        ng: _NewGenome,
        platform: str,
        platform_campaign_id: str,
    ) -> CycleAction:
        """Deploy a single variant to the ad platform (auto-deploy mode).

        Resolves media assets, calls adapter.create_ad(), inserts deployment
        record, and updates variant deployed_at timestamp.
        """
        # Calculate remaining budget
        remaining_row = await session.execute(
            text("SELECT remaining_budget(:id)"),
            {"id": campaign_id},
        )
        remaining = remaining_row.scalar_one()
        remaining_budget = Decimal(str(remaining)) if remaining is not None else Decimal("0")
        per_variant_budget = max(remaining_budget, Decimal("1.00"))

        # Resolve media asset
        media_info = None
        media_asset_name = ng.genome.get("media_asset")
        if media_asset_name:
            asset_row = await session.execute(
                text("""
                    SELECT asset_type, platform_id
                    FROM media_assets
                    WHERE campaign_id = :cid
                      AND name = :name
                      AND is_active = TRUE
                    LIMIT 1
                """),
                {"cid": campaign_id, "name": media_asset_name},
            )
            asset = asset_row.fetchone()
            if asset:
                media_info = {
                    "asset_type": str(asset[0]),
                    "platform_id": str(asset[1]),
                }

        # Deploy to platform
        platform_ad_id = await self._adapter.create_ad(
            campaign_id=platform_campaign_id,
            variant_code=variant_code,
            genome=ng.genome,
            daily_budget=float(per_variant_budget),
            media_info=media_info,
        )

        # Insert deployment record
        deployment_id = uuid.uuid4()
        await session.execute(
            text("""
                INSERT INTO deployments (id, variant_id, platform, platform_ad_id,
                                        daily_budget, is_active, created_at, updated_at)
                VALUES (:id, :variant_id, :platform, :platform_ad_id,
                        :daily_budget, TRUE, NOW(), NOW())
            """),
            {
                "id": deployment_id,
                "variant_id": variant_id,
                "platform": platform,
                "platform_ad_id": platform_ad_id,
                "daily_budget": per_variant_budget,
            },
        )

        # Update variant with deployed_at
        await session.execute(
            text("UPDATE variants SET deployed_at = NOW() WHERE id = :id"),
            {"id": variant_id},
        )

        logger.info(
            "Deployed variant %s (ad_id=%s) with budget %.2f",
            variant_code,
            platform_ad_id,
            per_variant_budget,
        )

        return CycleAction(
            variant_id=variant_id,
            action="launch",
            details={
                "variant_code": variant_code,
                "platform_ad_id": platform_ad_id,
                "daily_budget": float(per_variant_budget),
                "hypothesis": ng.hypothesis,
                "genome": ng.genome,
            },
        )

    async def _load_gene_pool(self, session: AsyncSession) -> GenePool:
        """Load the gene pool from the database and build a GenePool model."""

        rows = await session.execute(
            text(
                "SELECT slot_name, slot_value, description FROM gene_pool WHERE is_active = TRUE ORDER BY slot_name, slot_value"
            )
        )

        by_slot: dict[str, list[dict[str, str]]] = {}
        for row in rows.fetchall():
            slot_name = str(row[0])
            entry = {"value": str(row[1]), "description": str(row[2] or "")}
            by_slot.setdefault(slot_name, []).append(entry)

        return GenePool.model_validate(by_slot)

    async def _next_cycle_number(self, session: AsyncSession, campaign_id: uuid.UUID) -> int:
        """Get the next sequential cycle number for a campaign."""
        result = await session.execute(
            text("""
                SELECT COALESCE(MAX(cycle_number), 0) + 1
                FROM test_cycles
                WHERE campaign_id = :campaign_id
            """),
            {"campaign_id": campaign_id},
        )
        row = result.fetchone()
        return int(row[0]) if row else 1

    async def _update_cycle_phase(
        self, session: AsyncSession, cycle_id: uuid.UUID, phase: str
    ) -> None:
        """Update the phase column on the test_cycles record."""
        await session.execute(
            text("UPDATE test_cycles SET phase = :phase WHERE id = :id"),
            {"phase": phase, "id": cycle_id},
        )
        await session.flush()

    async def _log_action(
        self, session: AsyncSession, cycle_id: uuid.UUID, action: CycleAction
    ) -> None:
        """Insert a cycle_actions record."""
        await session.execute(
            text("""
                INSERT INTO cycle_actions (id, cycle_id, variant_id, action, details, executed_at)
                VALUES (:id, :cycle_id, :variant_id, :action, :details, NOW())
            """),
            {
                "id": uuid.uuid4(),
                "cycle_id": cycle_id,
                "variant_id": action.variant_id,
                "action": action.action,
                "details": json.dumps(action.details),
            },
        )

    async def _finalize_cycle(
        self,
        session: AsyncSession,
        cycle_id: uuid.UUID,
        report: CycleReport,
    ) -> None:
        """Update the test_cycles record with final stats."""
        error_log = json.dumps(report.errors) if report.errors else None

        await session.execute(
            text("""
                UPDATE test_cycles
                SET completed_at = NOW(),
                    variants_launched = :launched,
                    variants_paused = :paused,
                    variants_promoted = :promoted,
                    summary_text = :summary,
                    error_log = :error_log
                WHERE id = :id
            """),
            {
                "id": cycle_id,
                "launched": report.variants_launched,
                "paused": report.variants_paused,
                "promoted": report.variants_promoted,
                "summary": report.summary_text or None,
                "error_log": error_log,
            },
        )

    async def _get_platform_ad_id(self, session: AsyncSession, variant_id: uuid.UUID) -> str:
        """Look up the platform ad ID for a variant's active deployment."""
        result = await session.execute(
            text("""
                SELECT platform_ad_id FROM deployments
                WHERE variant_id = :variant_id AND is_active = TRUE
                LIMIT 1
            """),
            {"variant_id": variant_id},
        )
        row = result.fetchone()
        if not row:
            raise CycleError(
                phase="act",
                message=f"No active deployment found for variant {variant_id}",
            )
        return str(row[0])

    async def _get_daily_ctrs(
        self, session: AsyncSession, variant_id: uuid.UUID
    ) -> list[tuple[datetime, float]]:
        """Fetch daily CTR data for fatigue detection."""
        result = await session.execute(
            text("""
                SELECT time_bucket('1 day', recorded_at)::date AS day,
                       CASE WHEN MAX(impressions) > 0
                            THEN MAX(clicks)::float / MAX(impressions)
                            ELSE 0 END AS ctr
                FROM metrics
                WHERE variant_id = :variant_id
                GROUP BY day
                ORDER BY day
            """),
            {"variant_id": variant_id},
        )
        return [(row[0], float(row[1])) for row in result.fetchall()]

    def _build_summary(self, report: CycleReport) -> str:
        """Build a human-readable text summary of the cycle."""
        parts: list[str] = [
            f"Cycle #{report.cycle_number} for campaign {report.campaign_id}",
            f"Metrics collected: {report.snapshots_collected} snapshots",
        ]

        if report.variants_promoted > 0:
            parts.append(f"Winners found: {report.variants_promoted}")
        if report.variants_paused > 0:
            parts.append(f"Variants paused: {report.variants_paused}")
        if report.variants_launched > 0:
            parts.append(f"New variants launched: {report.variants_launched}")

        if report.errors:
            failed_phases = ", ".join(report.errors.keys())
            parts.append(f"Errors in phases: {failed_phases}")
        else:
            parts.append("All phases completed successfully.")

        return " | ".join(parts)


@dataclass(frozen=True)
class _VariantData:
    """Internal struct for variant metrics during analysis."""

    variant_id: uuid.UUID
    variant_code: str
    status: str
    genome: dict[str, str]
    impressions: int
    clicks: int
    conversions: int
    spend: float


@dataclass(frozen=True)
class _NewGenome:
    """Internal struct for a newly generated genome pending deployment."""

    genome: dict[str, str]
    hypothesis: str
    generation: int


def _format_error(exc: BaseException) -> str:
    """Format an exception for the error log."""
    return f"{type(exc).__name__}: {exc}\n{traceback.format_exc()}"
