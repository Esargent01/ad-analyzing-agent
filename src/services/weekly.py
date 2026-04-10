"""Weekly review flow: expires stale proposals, runs generation pass, and
builds ProposedVariant objects for the weekly report.

This is the glue between the existing GeneratorAgent + approval_queue
infrastructure and the weekly reporting cycle. It's called from the
``weekly-report`` CLI command.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID

import anthropic
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.agents.generator import GeneratorAgent, LLMError
from src.config import get_settings
from src.db.queries import (
    expire_stale_proposals,
    get_element_rankings,
    get_pending_approvals,
    get_top_interactions,
)
from src.db.tables import ApprovalActionType
from src.models.analysis import ElementInsight, InteractionInsight
from src.models.approvals import (
    PauseEvidence,
    PendingApproval,
    PendingNewVariant,
    PendingPauseVariant,
    PendingPromoteWinner,
    PendingScaleBudget,
    ScaleEvidence,
)
from src.models.genome import GenePool
from src.models.reports import ProposedVariant

logger = logging.getLogger(__name__)


async def _load_gene_pool(session: AsyncSession) -> GenePool:
    """Load the active gene pool from the database into a GenePool model."""
    rows = await session.execute(
        text(
            "SELECT slot_name, slot_value, description FROM gene_pool "
            "WHERE is_active = TRUE ORDER BY slot_name, slot_value"
        )
    )
    by_slot: dict[str, list[dict[str, str]]] = {}
    for row in rows.fetchall():
        slot_name = str(row[0])
        entry = {"value": str(row[1]), "description": str(row[2] or "")}
        by_slot.setdefault(slot_name, []).append(entry)
    return GenePool.model_validate(by_slot)


def _summarize_genome(genome: dict[str, str]) -> str:
    """Build a short human-readable summary of a genome for the report."""
    headline = genome.get("headline", "")
    cta = genome.get("cta_text", "")
    audience = genome.get("audience", "")
    parts = [p for p in (headline, cta, audience) if p]
    if not parts:
        return "—"
    # Truncate headline if too long
    if headline and len(headline) > 40:
        parts[0] = headline[:37] + "..."
    return " · ".join(parts)


async def run_weekly_generation(
    session: AsyncSession,
    campaign_id: UUID,
) -> tuple[int, bool]:
    """Run the weekly generation pass for a campaign.

    Steps:
    1. Expire stale pending proposals (>PROPOSAL_TTL_DAYS old)
    2. Compute remaining capacity (max - active - pending)
    3. If slots available, generate new variants via GeneratorAgent
    4. Create variant rows (status='pending') + approval_queue entries

    Returns (expired_count, generation_paused).
    generation_paused is True when the queue is at capacity and no
    new variants were generated.
    """
    settings = get_settings()

    # Step 1: expire stale pending proposals
    expired_count = await expire_stale_proposals(
        session, campaign_id, ttl_days=settings.proposal_ttl_days
    )
    if expired_count:
        logger.info("Expired %d stale proposals for campaign %s", expired_count, campaign_id)

    # Step 2: compute capacity
    max_row = await session.execute(
        text("SELECT max_concurrent_variants FROM campaigns WHERE id = :id"),
        {"id": campaign_id},
    )
    max_variants_row = max_row.fetchone()
    if not max_variants_row:
        logger.warning("Campaign %s not found during weekly generation", campaign_id)
        return 0, False
    max_variants = int(max_variants_row[0])

    active_row = await session.execute(
        text("SELECT COUNT(*) FROM variants WHERE campaign_id = :id AND status = 'active'"),
        {"id": campaign_id},
    )
    active_count = int(active_row.scalar_one())

    pending_row = await session.execute(
        text("SELECT COUNT(*) FROM approval_queue WHERE campaign_id = :id AND approved IS NULL"),
        {"id": campaign_id},
    )
    pending_count = int(pending_row.scalar_one())

    slots_available = max(0, max_variants - active_count - pending_count)
    if slots_available == 0:
        logger.info(
            "Weekly generation paused for campaign %s (max=%d, active=%d, pending=%d)",
            campaign_id,
            max_variants,
            active_count,
            pending_count,
        )
        return expired_count, True

    max_new = min(slots_available, 3)  # cap per-week generation at 3

    # Step 3: load context and call generator
    gene_pool = await _load_gene_pool(session)
    element_rankings_db = await get_element_rankings(session, campaign_id)
    top_interactions_db = await get_top_interactions(session, campaign_id)

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
        for ep in element_rankings_db
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
        for ei in top_interactions_db
    ]

    # Existing genomes: everything not retired (active, pending, paused, winner)
    existing_row = await session.execute(
        text("SELECT genome FROM variants WHERE campaign_id = :id AND status != 'retired'"),
        {"id": campaign_id},
    )
    existing_genomes: list[dict[str, str]] = []
    for row in existing_row.fetchall():
        genome = row[0]
        if isinstance(genome, dict):
            existing_genomes.append(genome)

    client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
    generator = GeneratorAgent(client=client, model=settings.anthropic_model)

    try:
        new_results = await generator.generate_variants(
            gene_pool=gene_pool,
            element_rankings=element_insights,
            top_interactions=interaction_insights,
            current_variants=existing_genomes,
            max_new=max_new,
        )
    except LLMError as exc:
        logger.warning("Weekly generator produced no valid variants: %s", exc)
        return expired_count, False

    # Step 4: create variant rows + approval_queue entries
    max_gen_row = await session.execute(
        text("SELECT COALESCE(MAX(generation), 0) FROM variants WHERE campaign_id = :id"),
        {"id": campaign_id},
    )
    current_max_gen = int(max_gen_row.scalar_one())
    next_generation = current_max_gen + 1

    for result in new_results:
        try:
            code_row = await session.execute(
                text("SELECT next_variant_code(:id)"),
                {"id": campaign_id},
            )
            variant_code = str(code_row.scalar_one())

            variant_id = uuid.uuid4()
            await session.execute(
                text(
                    """
                    INSERT INTO variants (id, campaign_id, variant_code, genome, status,
                                         generation, hypothesis, created_at)
                    VALUES (:id, :campaign_id, :variant_code, :genome, 'pending',
                            :generation, :hypothesis, NOW())
                    """
                ),
                {
                    "id": variant_id,
                    "campaign_id": campaign_id,
                    "variant_code": variant_code,
                    "genome": json.dumps(result.genome),
                    "generation": next_generation,
                    "hypothesis": result.hypothesis,
                },
            )

            await session.execute(
                text(
                    """
                    INSERT INTO approval_queue
                        (id, variant_id, campaign_id, genome_snapshot, hypothesis, submitted_at)
                    VALUES (:id, :variant_id, :campaign_id, :genome, :hypothesis, NOW())
                    """
                ),
                {
                    "id": uuid.uuid4(),
                    "variant_id": variant_id,
                    "campaign_id": campaign_id,
                    "genome": json.dumps(result.genome),
                    "hypothesis": result.hypothesis,
                },
            )
        except Exception as exc:  # noqa: BLE001 — tolerate individual failures
            logger.warning("Failed to queue weekly variant for genome %s: %s", result.genome, exc)

    await session.flush()
    logger.info(
        "Weekly generation queued %d variants for campaign %s",
        len(new_results),
        campaign_id,
    )
    return expired_count, False


async def load_proposed_variants(
    session: AsyncSession,
    campaign_id: UUID,
) -> list[ProposedVariant]:
    """Load pending ``new_variant`` proposals for a campaign (weekly report path).

    Phase H: the ``approval_queue`` now holds pause/scale proposals
    too. The weekly email report only cares about proposed new
    variants (the creative pipeline) so this loader filters down to
    ``action_type='new_variant'`` rows. The richer experiments page
    uses :func:`load_pending_approvals` to get the full discriminated
    union.

    Classification:
    - "new": submitted within the last 7 days
    - "expiring_soon": submitted 7+ days ago (user has a week before auto-reject)
    """
    settings = get_settings()
    ttl_days = settings.proposal_ttl_days
    now = datetime.now(UTC)
    expiring_threshold = now - timedelta(days=7)

    pending = await get_pending_approvals(session, campaign_id=campaign_id)
    pending = [
        p
        for p in pending
        if p.action_type == ApprovalActionType.new_variant and p.variant_id is not None
    ]

    # Pull variant codes in a single query
    variant_ids = [item.variant_id for item in pending]
    if not variant_ids:
        return []

    code_rows = await session.execute(
        text("SELECT id, variant_code FROM variants WHERE id = ANY(:ids)"),
        {"ids": variant_ids},
    )
    code_map: dict[UUID, str] = {row[0]: str(row[1]) for row in code_rows.fetchall()}

    proposed: list[ProposedVariant] = []
    for item in pending:
        submitted_at = item.submitted_at
        if submitted_at.tzinfo is None:
            submitted_at = submitted_at.replace(tzinfo=UTC)

        age_days = (now - submitted_at).days
        classification = "expiring_soon" if submitted_at < expiring_threshold else "new"
        days_until_expiry = max(0, ttl_days - age_days)

        genome = item.genome_snapshot if isinstance(item.genome_snapshot, dict) else {}

        proposed.append(
            ProposedVariant(
                approval_id=item.id,
                variant_id=item.variant_id,
                variant_code=code_map.get(item.variant_id, "—"),
                genome=genome,
                genome_summary=_summarize_genome(genome),
                hypothesis=item.hypothesis,
                submitted_at=submitted_at,
                classification=classification,
                days_until_expiry=days_until_expiry,
            )
        )

    # Sort: expiring_soon first, then by newest submission
    proposed.sort(
        key=lambda p: (0 if p.classification == "expiring_soon" else 1, -p.submitted_at.timestamp())
    )
    return proposed


async def load_pending_approvals(
    session: AsyncSession,
    campaign_id: UUID,
) -> list[PendingApproval]:
    """Return every pending approval for a campaign as a discriminated union.

    Phase H: the ``/experiments`` page renders a unified list of
    proposals — new variants, pause requests, budget changes — with
    different cards per kind. Each row is converted to the matching
    :class:`PendingApproval` branch so the frontend can discriminate
    on the ``kind`` literal.

    Sort order matches the DB query (pause → scale → new_variant →
    promote_winner), which is what ``get_pending_approvals`` already
    returns, so we preserve it rather than re-sorting here.
    """
    settings = get_settings()
    ttl_days = settings.proposal_ttl_days
    now = datetime.now(UTC)
    expiring_threshold = now - timedelta(days=7)

    pending = await get_pending_approvals(session, campaign_id=campaign_id)
    if not pending:
        return []

    # Resolve variant codes for rows that have one. pause/scale rows
    # don't own a variant_id but may reference a deployment — we
    # resolve those codes via a second query so the UI can still show
    # "pausing V7" rather than a raw deployment id.
    direct_variant_ids = [p.variant_id for p in pending if p.variant_id is not None]
    deployment_ids: list[str] = []
    for p in pending:
        payload = p.action_payload or {}
        did = payload.get("deployment_id")
        if did:
            deployment_ids.append(str(did))

    code_map: dict[UUID, str] = {}
    if direct_variant_ids:
        rows = await session.execute(
            text("SELECT id, variant_code FROM variants WHERE id = ANY(:ids)"),
            {"ids": direct_variant_ids},
        )
        for row in rows.fetchall():
            code_map[row[0]] = str(row[1])

    deployment_variant_code: dict[str, str] = {}
    if deployment_ids:
        rows = await session.execute(
            text(
                """
                SELECT d.id::text, v.variant_code
                FROM deployments d
                JOIN variants v ON v.id = d.variant_id
                WHERE d.id = ANY(:ids)
                """
            ),
            {"ids": deployment_ids},
        )
        for row in rows.fetchall():
            deployment_variant_code[str(row[0])] = str(row[1])

    items: list[PendingApproval] = []
    for p in pending:
        submitted_at = p.submitted_at
        if submitted_at.tzinfo is None:
            submitted_at = submitted_at.replace(tzinfo=UTC)
        payload = p.action_payload or {}
        genome = p.genome_snapshot if isinstance(p.genome_snapshot, dict) else {}

        if p.action_type == ApprovalActionType.new_variant:
            age_days = (now - submitted_at).days
            classification = "expiring_soon" if submitted_at < expiring_threshold else "new"
            days_until_expiry = max(0, ttl_days - age_days)
            items.append(
                PendingNewVariant(
                    approval_id=p.id,
                    variant_id=p.variant_id,
                    variant_code=code_map.get(p.variant_id, "—") if p.variant_id else "—",
                    genome=genome,
                    genome_summary=_summarize_genome(genome),
                    hypothesis=p.hypothesis,
                    submitted_at=submitted_at,
                    classification=classification,
                    days_until_expiry=days_until_expiry,
                )
            )
        elif p.action_type == ApprovalActionType.pause_variant:
            deployment_id = payload.get("deployment_id")
            platform_ad_id = payload.get("platform_ad_id", "")
            reason = payload.get("reason", "statistically_significant_loser")
            evidence_raw = payload.get("evidence") or {}
            evidence_raw = {**evidence_raw, "reason": reason}
            items.append(
                PendingPauseVariant(
                    approval_id=p.id,
                    campaign_id=p.campaign_id,
                    deployment_id=deployment_id,
                    platform_ad_id=platform_ad_id,
                    variant_code=deployment_variant_code.get(str(deployment_id)),
                    genome_snapshot=genome,
                    reason=reason,
                    evidence=PauseEvidence.model_validate(evidence_raw),
                    submitted_at=submitted_at,
                )
            )
        elif p.action_type == ApprovalActionType.scale_budget:
            deployment_id = payload.get("deployment_id")
            platform_ad_id = payload.get("platform_ad_id", "")
            current_budget = payload.get("current_budget", 0)
            proposed_budget = payload.get("proposed_budget", 0)
            evidence_raw = payload.get("evidence") or {}
            items.append(
                PendingScaleBudget(
                    approval_id=p.id,
                    campaign_id=p.campaign_id,
                    deployment_id=deployment_id,
                    platform_ad_id=platform_ad_id,
                    variant_code=deployment_variant_code.get(str(deployment_id)),
                    genome_snapshot=genome,
                    current_budget=Decimal(str(current_budget)),
                    proposed_budget=Decimal(str(proposed_budget)),
                    reason=payload.get("reason", "thompson_sampling"),
                    evidence=ScaleEvidence.model_validate(evidence_raw),
                    submitted_at=submitted_at,
                )
            )
        elif p.action_type == ApprovalActionType.promote_winner:
            items.append(
                PendingPromoteWinner(
                    approval_id=p.id,
                    variant_id=p.variant_id,
                    variant_code=code_map.get(p.variant_id, "—") if p.variant_id else "—",
                    submitted_at=submitted_at,
                )
            )

    return items
