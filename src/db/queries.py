"""Standalone async query functions for the ad creative agent system.

All functions accept an AsyncSession as the first argument and use
SQLAlchemy's select() construct. No raw SQL.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID

from sqlalchemy import Integer, case, func, select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.tables import (
    ActionType,
    ApprovalActionType,
    ApprovalQueueItem,
    Campaign,
    CycleAction,
    DataDeletionRequest,
    Deployment,
    ElementInteraction,
    ElementPerformance,
    GenePoolEntry,
    MagicLinkConsumed,
    Metric,
    TestCycle,
    User,
    UserCampaign,
    UserMetaConnection,
    Variant,
    VariantStatus,
)
from src.exceptions import BudgetExceededError

# ---------------------------------------------------------------------------
# Gene pool
# ---------------------------------------------------------------------------


async def get_active_gene_pool(session: AsyncSession) -> list[GenePoolEntry]:
    """Return all active gene pool entries, ordered by slot name and value."""
    stmt = (
        select(GenePoolEntry)
        .where(GenePoolEntry.is_active.is_(True))
        .order_by(GenePoolEntry.slot_name, GenePoolEntry.slot_value)
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def get_gene_pool_by_slot(session: AsyncSession) -> dict[str, list[GenePoolEntry]]:
    """Return active gene pool entries grouped by slot name."""
    entries = await get_active_gene_pool(session)
    by_slot: dict[str, list[GenePoolEntry]] = {}
    for entry in entries:
        by_slot.setdefault(entry.slot_name, []).append(entry)
    return by_slot


async def list_gene_pool_entries(
    session: AsyncSession,
    slot_name: str | None = None,
    include_inactive: bool = False,
) -> list[GenePoolEntry]:
    """Return gene pool entries, optionally filtered by slot and active status."""
    stmt = select(GenePoolEntry).order_by(GenePoolEntry.slot_name, GenePoolEntry.slot_value)
    if slot_name is not None:
        stmt = stmt.where(GenePoolEntry.slot_name == slot_name)
    if not include_inactive:
        stmt = stmt.where(GenePoolEntry.is_active.is_(True))
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def add_gene_pool_entry(
    session: AsyncSession,
    slot_name: str,
    slot_value: str,
    description: str | None = None,
    metadata: dict | None = None,
    source: str = "user",
) -> GenePoolEntry:
    """Add a new gene pool entry. Raises IntegrityError on duplicate (slot_name, slot_value)."""
    entry = GenePoolEntry(
        slot_name=slot_name,
        slot_value=slot_value,
        description=description,
        metadata_=metadata,
        source=source,
        is_active=source != "llm_suggested",  # LLM suggestions start inactive
    )
    session.add(entry)
    await session.flush()
    return entry


async def deactivate_gene_pool_entry(
    session: AsyncSession,
    slot_name: str,
    slot_value: str,
) -> bool:
    """Retire a gene pool entry. Returns False if not found."""
    stmt = select(GenePoolEntry).where(
        GenePoolEntry.slot_name == slot_name,
        GenePoolEntry.slot_value == slot_value,
        GenePoolEntry.is_active.is_(True),
    )
    result = await session.execute(stmt)
    entry = result.scalar_one_or_none()
    if entry is None:
        return False
    entry.is_active = False
    entry.retired_at = func.now()
    await session.flush()
    return True


async def get_pending_suggestions(session: AsyncSession) -> list[GenePoolEntry]:
    """Return LLM-suggested gene pool entries awaiting approval."""
    stmt = (
        select(GenePoolEntry)
        .where(
            GenePoolEntry.source == "llm_suggested",
            GenePoolEntry.is_active.is_(False),
            GenePoolEntry.retired_at.is_(None),
        )
        .order_by(GenePoolEntry.slot_name, GenePoolEntry.created_at)
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def approve_suggestion(session: AsyncSession, entry_id: UUID) -> GenePoolEntry | None:
    """Activate a pending LLM suggestion, returning None if not found."""
    stmt = select(GenePoolEntry).where(GenePoolEntry.id == entry_id)
    result = await session.execute(stmt)
    entry = result.scalar_one_or_none()
    if entry is None:
        return None
    entry.is_active = True
    entry.source = "llm_approved"
    await session.flush()
    return entry


async def reject_suggestion(session: AsyncSession, entry_id: UUID) -> bool:
    """Mark a pending LLM suggestion as rejected (retired). Returns False if not found."""
    stmt = select(GenePoolEntry).where(GenePoolEntry.id == entry_id)
    result = await session.execute(stmt)
    entry = result.scalar_one_or_none()
    if entry is None:
        return False
    entry.retired_at = func.now()
    await session.flush()
    return True


async def get_gene_pool_entry(
    session: AsyncSession,
    slot_name: str,
    slot_value: str,
) -> GenePoolEntry | None:
    """Look up a single active gene pool entry by slot name and value."""
    stmt = select(GenePoolEntry).where(
        GenePoolEntry.slot_name == slot_name,
        GenePoolEntry.slot_value == slot_value,
        GenePoolEntry.is_active.is_(True),
    )
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


# ---------------------------------------------------------------------------
# Campaigns
# ---------------------------------------------------------------------------


async def get_campaign(session: AsyncSession, campaign_id: UUID) -> Campaign | None:
    """Return a campaign by ID, or None if not found."""
    stmt = select(Campaign).where(Campaign.id == campaign_id)
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def get_active_campaigns(session: AsyncSession) -> list[Campaign]:
    """Return all active campaigns."""
    stmt = select(Campaign).where(Campaign.is_active.is_(True))
    result = await session.execute(stmt)
    return list(result.scalars().all())


# ---------------------------------------------------------------------------
# Variants
# ---------------------------------------------------------------------------


async def get_active_variants(session: AsyncSession, campaign_id: UUID) -> list[Variant]:
    """Return all active variants for a campaign."""
    stmt = (
        select(Variant)
        .where(
            Variant.campaign_id == campaign_id,
            Variant.status == VariantStatus.active,
        )
        .order_by(Variant.variant_code)
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def get_variants_by_status(
    session: AsyncSession,
    campaign_id: UUID,
    statuses: list[VariantStatus],
) -> list[Variant]:
    """Return variants matching any of the given statuses."""
    stmt = (
        select(Variant)
        .where(
            Variant.campaign_id == campaign_id,
            Variant.status.in_(statuses),
        )
        .order_by(Variant.variant_code)
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def create_variant(
    session: AsyncSession,
    campaign_id: UUID,
    genome: dict[str, str],
    hypothesis: str | None,
    parent_ids: list[UUID] | None = None,
    generation: int = 1,
) -> Variant:
    """Create a new variant with the next available variant code.

    Uses the next_variant_code() database function to generate codes
    like V1, V2, etc.
    """
    # Get the next variant code via a subquery
    next_code_stmt = select(
        func.coalesce(
            func.max(
                func.nullif(
                    func.regexp_replace(Variant.variant_code, "[^0-9]", "", "g"),
                    "",
                ).cast(Integer)
            ),
            0,
        )
        + 1
    ).where(Variant.campaign_id == campaign_id)

    result = await session.execute(next_code_stmt)
    next_number = result.scalar_one()
    variant_code = f"V{next_number}"

    variant = Variant(
        campaign_id=campaign_id,
        variant_code=variant_code,
        genome=genome,
        hypothesis=hypothesis,
        parent_ids=parent_ids or [],
        generation=generation,
    )
    session.add(variant)
    await session.flush()
    return variant


async def update_variant_status(
    session: AsyncSession,
    variant_id: UUID,
    new_status: VariantStatus,
) -> Variant | None:
    """Update a variant's status and set corresponding timestamp fields."""
    stmt = select(Variant).where(Variant.id == variant_id)
    result = await session.execute(stmt)
    variant = result.scalar_one_or_none()
    if variant is None:
        return None

    variant.status = new_status
    now = datetime.utcnow()

    if new_status == VariantStatus.active:
        variant.deployed_at = now
    elif new_status == VariantStatus.paused:
        variant.paused_at = now
    elif new_status == VariantStatus.retired:
        variant.retired_at = now

    await session.flush()
    return variant


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------


async def get_variant_metrics(
    session: AsyncSession,
    variant_id: UUID,
    since: datetime,
) -> list[Metric]:
    """Return all metric snapshots for a variant since the given timestamp."""
    stmt = (
        select(Metric)
        .where(
            Metric.variant_id == variant_id,
            Metric.recorded_at >= since,
        )
        .order_by(Metric.recorded_at.asc())
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def get_latest_metrics(session: AsyncSession, variant_id: UUID) -> Metric | None:
    """Return the most recent metric snapshot for a variant."""
    stmt = (
        select(Metric)
        .where(Metric.variant_id == variant_id)
        .order_by(Metric.recorded_at.desc())
        .limit(1)
    )
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


# ---------------------------------------------------------------------------
# Element performance
# ---------------------------------------------------------------------------


async def upsert_element_performance(
    session: AsyncSession,
    campaign_id: UUID,
    slot_name: str,
    slot_value: str,
    stats: dict,
) -> ElementPerformance:
    """Insert or update element performance stats.

    ``stats`` should contain keys like: variants_tested, avg_ctr, avg_cpa,
    best_ctr, worst_ctr, total_impressions, total_conversions, confidence.
    """
    stmt = (
        pg_insert(ElementPerformance)
        .values(
            campaign_id=campaign_id,
            slot_name=slot_name,
            slot_value=slot_value,
            variants_tested=stats.get("variants_tested", 0),
            avg_ctr=stats.get("avg_ctr"),
            avg_cpa=stats.get("avg_cpa"),
            best_ctr=stats.get("best_ctr"),
            worst_ctr=stats.get("worst_ctr"),
            total_impressions=stats.get("total_impressions", 0),
            total_conversions=stats.get("total_conversions", 0),
            confidence=stats.get("confidence"),
            last_tested_at=func.now(),
            updated_at=func.now(),
        )
        .on_conflict_do_update(
            constraint="uq_element_perf_campaign_slot",
            set_={
                "variants_tested": stats.get("variants_tested", 0),
                "avg_ctr": stats.get("avg_ctr"),
                "avg_cpa": stats.get("avg_cpa"),
                "best_ctr": stats.get("best_ctr"),
                "worst_ctr": stats.get("worst_ctr"),
                "total_impressions": stats.get("total_impressions", 0),
                "total_conversions": stats.get("total_conversions", 0),
                "confidence": stats.get("confidence"),
                "last_tested_at": func.now(),
                "updated_at": func.now(),
            },
        )
        .returning(ElementPerformance)
    )
    result = await session.execute(stmt)
    return result.scalar_one()


async def get_element_rankings(
    session: AsyncSession,
    campaign_id: UUID,
) -> list[ElementPerformance]:
    """Return element performance data for a campaign, ranked by CTR within each slot.

    Only includes elements tested in 2+ variants.
    """
    stmt = (
        select(ElementPerformance)
        .where(
            ElementPerformance.campaign_id == campaign_id,
            ElementPerformance.variants_tested >= 2,
        )
        .order_by(ElementPerformance.slot_name, ElementPerformance.avg_ctr.desc().nulls_last())
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


# ---------------------------------------------------------------------------
# Element interactions
# ---------------------------------------------------------------------------


async def upsert_element_interaction(
    session: AsyncSession,
    campaign_id: UUID,
    slot_a_name: str,
    slot_a_value: str,
    slot_b_name: str,
    slot_b_value: str,
    stats: dict,
) -> ElementInteraction:
    """Insert or update an element interaction record.

    Enforces canonical ordering: slot_a_name < slot_b_name
    (or same slot with slot_a_value < slot_b_value).
    Caller must provide pairs in canonical order.

    ``stats`` should contain keys like: variants_tested, combined_avg_ctr,
    solo_a_avg_ctr, solo_b_avg_ctr, interaction_lift, confidence.
    """
    stmt = (
        pg_insert(ElementInteraction)
        .values(
            campaign_id=campaign_id,
            slot_a_name=slot_a_name,
            slot_a_value=slot_a_value,
            slot_b_name=slot_b_name,
            slot_b_value=slot_b_value,
            variants_tested=stats.get("variants_tested", 0),
            combined_avg_ctr=stats.get("combined_avg_ctr"),
            solo_a_avg_ctr=stats.get("solo_a_avg_ctr"),
            solo_b_avg_ctr=stats.get("solo_b_avg_ctr"),
            interaction_lift=stats.get("interaction_lift"),
            confidence=stats.get("confidence"),
            updated_at=func.now(),
        )
        .on_conflict_do_update(
            constraint="uq_interaction_pair",
            set_={
                "variants_tested": stats.get("variants_tested", 0),
                "combined_avg_ctr": stats.get("combined_avg_ctr"),
                "solo_a_avg_ctr": stats.get("solo_a_avg_ctr"),
                "solo_b_avg_ctr": stats.get("solo_b_avg_ctr"),
                "interaction_lift": stats.get("interaction_lift"),
                "confidence": stats.get("confidence"),
                "updated_at": func.now(),
            },
        )
        .returning(ElementInteraction)
    )
    result = await session.execute(stmt)
    return result.scalar_one()


async def get_top_interactions(
    session: AsyncSession,
    campaign_id: UUID,
    min_confidence: Decimal = Decimal("85.00"),
    limit: int = 20,
) -> list[ElementInteraction]:
    """Return the top element interactions by absolute lift for a campaign.

    Only includes interactions with confidence >= min_confidence.
    """
    stmt = (
        select(ElementInteraction)
        .where(
            ElementInteraction.campaign_id == campaign_id,
            ElementInteraction.confidence >= min_confidence,
        )
        .order_by(func.abs(ElementInteraction.interaction_lift).desc())
        .limit(limit)
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


# ---------------------------------------------------------------------------
# Budget
# ---------------------------------------------------------------------------


async def get_remaining_budget(session: AsyncSession, campaign_id: UUID) -> Decimal:
    """Calculate remaining daily budget capacity for a campaign.

    Returns the campaign's daily_budget minus the sum of daily_budget
    allocated to active deployments of active variants.
    """
    # Get campaign budget
    campaign_stmt = select(Campaign.daily_budget).where(Campaign.id == campaign_id)
    campaign_result = await session.execute(campaign_stmt)
    daily_budget = campaign_result.scalar_one_or_none()
    if daily_budget is None:
        return Decimal("0.00")

    # Sum allocated budgets from active deployments of active variants
    allocated_stmt = (
        select(func.coalesce(func.sum(Deployment.daily_budget), Decimal("0.00")))
        .join(Variant, Deployment.variant_id == Variant.id)
        .where(
            Variant.campaign_id == campaign_id,
            Variant.status == VariantStatus.active,
            Deployment.is_active.is_(True),
        )
    )
    allocated_result = await session.execute(allocated_stmt)
    allocated = allocated_result.scalar_one()

    return daily_budget - allocated


# ---------------------------------------------------------------------------
# Test cycles
# ---------------------------------------------------------------------------


async def create_cycle(
    session: AsyncSession,
    campaign_id: UUID,
    cycle_number: int,
) -> TestCycle:
    """Create a new test cycle record."""
    cycle = TestCycle(
        campaign_id=campaign_id,
        cycle_number=cycle_number,
    )
    session.add(cycle)
    await session.flush()
    return cycle


async def update_cycle_phase(
    session: AsyncSession,
    cycle_id: UUID,
    phase: str,
) -> None:
    """Update the phase of a test cycle."""
    from src.db.tables import CyclePhase

    stmt = update(TestCycle).where(TestCycle.id == cycle_id).values(phase=CyclePhase(phase))
    await session.execute(stmt)
    await session.flush()


async def complete_cycle(
    session: AsyncSession,
    cycle_id: UUID,
    stats: dict,
) -> None:
    """Mark a test cycle as complete with summary statistics.

    ``stats`` should contain keys like: variants_active, variants_launched,
    variants_paused, variants_promoted, total_spend, avg_ctr, avg_cpa,
    summary_text, error_log.
    """
    from src.db.tables import CyclePhase

    stmt = (
        update(TestCycle)
        .where(TestCycle.id == cycle_id)
        .values(
            phase=CyclePhase.complete,
            completed_at=func.now(),
            variants_active=stats.get("variants_active"),
            variants_launched=stats.get("variants_launched", 0),
            variants_paused=stats.get("variants_paused", 0),
            variants_promoted=stats.get("variants_promoted", 0),
            total_spend=stats.get("total_spend"),
            avg_ctr=stats.get("avg_ctr"),
            avg_cpa=stats.get("avg_cpa"),
            summary_text=stats.get("summary_text"),
            error_log=stats.get("error_log"),
        )
    )
    await session.execute(stmt)
    await session.flush()


# ---------------------------------------------------------------------------
# Cycle actions
# ---------------------------------------------------------------------------


async def log_cycle_action(
    session: AsyncSession,
    cycle_id: UUID,
    variant_id: UUID | None,
    action: ActionType,
    details: dict | None = None,
) -> CycleAction:
    """Record an action taken during a test cycle."""
    cycle_action = CycleAction(
        cycle_id=cycle_id,
        variant_id=variant_id,
        action=action,
        details=details,
    )
    session.add(cycle_action)
    await session.flush()
    return cycle_action


async def get_cycle_actions(session: AsyncSession, cycle_id: UUID) -> list[CycleAction]:
    """Return all actions for a given test cycle."""
    stmt = (
        select(CycleAction)
        .where(CycleAction.cycle_id == cycle_id)
        .order_by(CycleAction.executed_at)
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def get_latest_cycle(
    session: AsyncSession,
    campaign_id: UUID,
) -> TestCycle | None:
    """Return the most recent test cycle for a campaign."""
    stmt = (
        select(TestCycle)
        .where(TestCycle.campaign_id == campaign_id)
        .order_by(TestCycle.cycle_number.desc())
        .limit(1)
    )
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def get_recent_cycles(
    session: AsyncSession,
    campaign_id: UUID,
    limit: int = 10,
) -> list[TestCycle]:
    """Return the most recent test cycles for a campaign."""
    stmt = (
        select(TestCycle)
        .where(TestCycle.campaign_id == campaign_id)
        .order_by(TestCycle.cycle_number.desc())
        .limit(limit)
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


# ---------------------------------------------------------------------------
# Approval queue
# ---------------------------------------------------------------------------
#
# Phase H note: this queue used to hold only "proposed new variant" rows.
# It now holds four kinds of proposals: ``new_variant``, ``pause_variant``,
# ``scale_budget``, and ``promote_winner``. The variant-scoped helpers
# (``submit_for_approval``, ``approve_variant``, ``reject_variant``) stay
# for backwards compatibility with callers that still think in variants,
# and call through to the generalized ``approve_proposal`` /
# ``reject_proposal`` underneath. New callers should prefer the
# generalized helpers.


async def submit_for_approval(
    session: AsyncSession,
    variant_id: UUID,
    campaign_id: UUID,
    genome: dict[str, str],
    hypothesis: str | None = None,
) -> ApprovalQueueItem:
    """Insert a ``new_variant`` proposal into the approval queue.

    Phase-H shim: existing callers (the orchestrator's generate phase,
    the weekly flow) still think of approvals as "a new variant wants a
    review". This helper preserves that spelling. Under the hood every
    row carries ``action_type='new_variant'`` and an empty payload.
    """
    item = ApprovalQueueItem(
        variant_id=variant_id,
        campaign_id=campaign_id,
        genome_snapshot=genome,
        hypothesis=hypothesis,
        action_type=ApprovalActionType.new_variant,
        action_payload={},
    )
    session.add(item)
    await session.flush()
    return item


async def has_open_proposal(
    session: AsyncSession,
    *,
    deployment_id: UUID,
    action_type: ApprovalActionType,
) -> bool:
    """Return True if a pending proposal already exists for this (deployment, action_type).

    Used by the orchestrator to stay idempotent across cycles — if the
    stats say "pause ad X" twice in a row, we shouldn't queue the same
    proposal each time. Checks via JSONB containment on
    ``action_payload->>'deployment_id'`` because deployment references
    for non-variant actions live in the payload, not in a dedicated
    column.
    """
    stmt = (
        select(ApprovalQueueItem.id)
        .where(ApprovalQueueItem.action_type == action_type)
        .where(ApprovalQueueItem.approved.is_(None))
        .where(ApprovalQueueItem.action_payload["deployment_id"].astext == str(deployment_id))
        .limit(1)
    )
    result = await session.execute(stmt)
    return result.scalar_one_or_none() is not None


async def queue_pause_proposal(
    session: AsyncSession,
    *,
    campaign_id: UUID,
    deployment_id: UUID,
    platform_ad_id: str,
    reason: str,
    evidence: dict,
    genome_snapshot: dict[str, str] | None = None,
    hypothesis: str | None = None,
) -> UUID | None:
    """Queue a pause proposal for a currently-running deployment.

    Returns the new approval_queue row id, or ``None`` if an open pause
    proposal already exists for this deployment (idempotent dedupe).

    ``genome_snapshot`` is accepted but optional — the column is still
    NOT NULL from the pre-Phase-H schema, so we fall back to an empty
    dict rather than change the column. Callers that have the variant's
    current genome handy (the orchestrator does) should pass it so the
    approval card can show "pause this ad: <copy>" without a second
    lookup.
    """
    if await has_open_proposal(
        session,
        deployment_id=deployment_id,
        action_type=ApprovalActionType.pause_variant,
    ):
        return None

    payload = {
        "deployment_id": str(deployment_id),
        "platform_ad_id": platform_ad_id,
        "reason": reason,
        "evidence": evidence,
    }
    item = ApprovalQueueItem(
        variant_id=None,
        campaign_id=campaign_id,
        genome_snapshot=genome_snapshot or {},
        hypothesis=hypothesis,
        action_type=ApprovalActionType.pause_variant,
        action_payload=payload,
    )
    session.add(item)
    await session.flush()
    return item.id


async def queue_scale_proposal(
    session: AsyncSession,
    *,
    campaign_id: UUID,
    deployment_id: UUID,
    platform_ad_id: str,
    current_budget: Decimal,
    proposed_budget: Decimal,
    evidence: dict,
    reason: str = "thompson_sampling",
    genome_snapshot: dict[str, str] | None = None,
    hypothesis: str | None = None,
) -> UUID | None:
    """Queue a budget-change proposal for a currently-running deployment.

    Returns the new approval_queue row id, or ``None`` if an open scale
    proposal already exists for this deployment. If a prior scale
    proposal exists but its ``proposed_budget`` is identical to the new
    one, we still dedupe — the user hasn't acted yet and re-queuing
    wouldn't change anything. Callers that need to override the
    existing proposal (e.g. a follow-up cycle computed a meaningfully
    different number) should reject the stale row first.
    """
    if await has_open_proposal(
        session,
        deployment_id=deployment_id,
        action_type=ApprovalActionType.scale_budget,
    ):
        return None

    # ---- Budget guardrail: reject proposals that would exceed the
    # campaign's daily budget. This is the first line of defence;
    # ``_execute_scale`` re-validates before calling Meta.
    campaign_row = await session.execute(
        select(Campaign.daily_budget).where(Campaign.id == campaign_id)
    )
    campaign_daily = campaign_row.scalar_one_or_none()
    if campaign_daily is not None and proposed_budget > campaign_daily:
        raise BudgetExceededError(
            f"Proposed budget ${proposed_budget} exceeds campaign daily limit ${campaign_daily}"
        )
    if campaign_daily is not None:
        remaining = await get_remaining_budget(session, campaign_id)
        budget_increase = proposed_budget - current_budget
        if budget_increase > Decimal("0") and budget_increase > remaining:
            raise BudgetExceededError(
                f"Budget increase ${budget_increase} exceeds remaining "
                f"campaign capacity ${remaining}"
            )

    payload = {
        "deployment_id": str(deployment_id),
        "platform_ad_id": platform_ad_id,
        "current_budget": float(current_budget),
        "proposed_budget": float(proposed_budget),
        "reason": reason,
        "evidence": evidence,
    }
    item = ApprovalQueueItem(
        variant_id=None,
        campaign_id=campaign_id,
        genome_snapshot=genome_snapshot or {},
        hypothesis=hypothesis,
        action_type=ApprovalActionType.scale_budget,
        action_payload=payload,
    )
    session.add(item)
    await session.flush()
    return item.id


async def get_pending_approvals(
    session: AsyncSession,
    campaign_id: UUID | None = None,
) -> list[ApprovalQueueItem]:
    """Return approval queue items awaiting review (approved IS NULL).

    Phase H: ordered so pause proposals surface first (they're blocking
    bad ads), then scale proposals, then new variants / promotions.
    Within each action_type the oldest row wins — a proposal sitting
    longer deserves attention sooner.
    """
    # Rank action types so pause > scale > new_variant > promote_winner.
    # Using a CASE expression keeps the sort in the DB rather than
    # re-sorting in Python, and avoids casting the enum column.
    type_rank = case(
        (ApprovalQueueItem.action_type == ApprovalActionType.pause_variant, 0),
        (ApprovalQueueItem.action_type == ApprovalActionType.scale_budget, 1),
        (ApprovalQueueItem.action_type == ApprovalActionType.new_variant, 2),
        (ApprovalQueueItem.action_type == ApprovalActionType.promote_winner, 3),
        else_=4,
    )
    stmt = (
        select(ApprovalQueueItem)
        .where(ApprovalQueueItem.approved.is_(None))
        .order_by(type_rank, ApprovalQueueItem.submitted_at)
    )
    if campaign_id is not None:
        stmt = stmt.where(ApprovalQueueItem.campaign_id == campaign_id)
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def get_pending_approvals_for_campaigns(
    session: AsyncSession,
    campaign_ids: list[UUID],
) -> list[ApprovalQueueItem]:
    """Return pending approvals for multiple campaigns at once.

    Same ordering as :func:`get_pending_approvals` (pause first, oldest
    within each type) but scoped to *campaign_ids*. Used by the dashboard
    ``/api/approvals`` endpoint to show a user only their own approvals.
    """
    if not campaign_ids:
        return []
    type_rank = case(
        (ApprovalQueueItem.action_type == ApprovalActionType.pause_variant, 0),
        (ApprovalQueueItem.action_type == ApprovalActionType.scale_budget, 1),
        (ApprovalQueueItem.action_type == ApprovalActionType.new_variant, 2),
        (ApprovalQueueItem.action_type == ApprovalActionType.promote_winner, 3),
        else_=4,
    )
    stmt = (
        select(ApprovalQueueItem)
        .where(
            ApprovalQueueItem.approved.is_(None),
            ApprovalQueueItem.campaign_id.in_(campaign_ids),
        )
        .order_by(type_rank, ApprovalQueueItem.submitted_at)
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def approve_proposal(
    session: AsyncSession,
    approval_id: UUID,
    reviewer: str = "cli",
) -> ApprovalQueueItem | None:
    """Mark a queued proposal as approved and return the row.

    This does **not** perform the Meta mutation — the HTTP handler calls
    ``src.services.approval_executor.execute_approved_action`` after
    this returns to actually pause/scale/deploy. Splitting flip-flag
    from side-effect lets the executor roll back the approval if Meta
    rejects the change.

    Idempotency: if the row is already approved **and** ``executed_at``
    is set, returns the row unchanged (double-click protection). If
    approved but ``executed_at`` is NULL we return it as-is too, so the
    caller can re-run the executor for the pending-execution case.
    """
    item = await session.get(ApprovalQueueItem, approval_id)
    if item is None:
        return None
    if item.approved is True:
        # Already approved — let the caller decide whether to re-execute.
        return item
    item.approved = True
    item.reviewed_at = func.now()
    item.reviewer = reviewer
    await session.flush()
    return item


async def mark_proposal_executed(
    session: AsyncSession,
    approval_id: UUID,
) -> None:
    """Stamp ``executed_at`` once the Meta side-effect has landed.

    Called from the approval executor after a successful adapter call.
    Separate from ``approve_proposal`` so approval can persist while
    execution is in-flight and the DB reflects that gap.
    """
    stmt = (
        update(ApprovalQueueItem)
        .where(ApprovalQueueItem.id == approval_id)
        .values(executed_at=func.now())
    )
    await session.execute(stmt)
    await session.flush()


async def reject_proposal(
    session: AsyncSession,
    approval_id: UUID,
    reason: str,
    reviewer: str = "cli",
) -> ApprovalQueueItem | None:
    """Reject a queued proposal. Only retires a variant for variant-scoped rows.

    For ``pause_variant`` / ``scale_budget`` proposals there's no
    variant row to retire — the running ad stays running, we're just
    telling the system "don't do this". For ``new_variant`` /
    ``promote_winner`` we still retire the associated variant so it
    doesn't sit as a zombie draft.
    """
    item = await session.get(ApprovalQueueItem, approval_id)
    if item is None:
        return None
    item.approved = False
    item.reviewed_at = func.now()
    item.reviewer = reviewer
    item.rejection_reason = reason

    variant_scoped = item.action_type in (
        ApprovalActionType.new_variant,
        ApprovalActionType.promote_winner,
    )
    if variant_scoped and item.variant_id is not None:
        variant = await session.get(Variant, item.variant_id)
        if variant is not None:
            variant.status = VariantStatus.retired
            variant.retired_at = func.now()

    await session.flush()
    return item


# Back-compat shims ---------------------------------------------------------
#
# Older callers (CLI, existing tests) still use ``approve_variant`` /
# ``reject_variant``. Keep them as thin wrappers around the generalized
# helpers so we don't churn every site in this PR.


async def approve_variant(
    session: AsyncSession,
    approval_id: UUID,
    reviewer: str = "cli",
) -> ApprovalQueueItem | None:
    """Back-compat wrapper for ``approve_proposal``."""
    return await approve_proposal(session, approval_id, reviewer=reviewer)


async def reject_variant(
    session: AsyncSession,
    approval_id: UUID,
    reason: str,
    reviewer: str = "cli",
) -> ApprovalQueueItem | None:
    """Back-compat wrapper for ``reject_proposal``."""
    return await reject_proposal(session, approval_id, reason, reviewer=reviewer)


async def expire_stale_proposals(
    session: AsyncSession,
    campaign_id: UUID,
    ttl_days: int = 14,
) -> int:
    """Auto-reject pending approval queue items older than ttl_days.

    Called at the start of the weekly flow to prevent stale proposals
    from piling up. Phase H: only retires the associated variant for
    variant-scoped rows — pause/scale expirations are a no-op against
    the running ad (we just drop the stale proposal).
    """
    cutoff = datetime.now(UTC) - timedelta(days=ttl_days)
    stmt = (
        select(ApprovalQueueItem)
        .where(ApprovalQueueItem.campaign_id == campaign_id)
        .where(ApprovalQueueItem.approved.is_(None))
        .where(ApprovalQueueItem.submitted_at < cutoff)
    )
    result = await session.execute(stmt)
    stale_items = list(result.scalars().all())

    for item in stale_items:
        item.approved = False
        item.reviewed_at = func.now()
        item.reviewer = "system"
        item.rejection_reason = "expired_no_review"

        variant_scoped = item.action_type in (
            ApprovalActionType.new_variant,
            ApprovalActionType.promote_winner,
        )
        if variant_scoped and item.variant_id is not None:
            variant = await session.get(Variant, item.variant_id)
            if variant is not None:
                variant.status = VariantStatus.retired
                variant.retired_at = func.now()

    await session.flush()
    return len(stale_items)


# ---------------------------------------------------------------------------
# Dashboard users (Phase 2 auth)
# ---------------------------------------------------------------------------


def _normalize_email(email: str) -> str:
    """Lowercase and strip an email for consistent lookups."""
    return email.strip().lower()


async def get_user_by_email(session: AsyncSession, email: str) -> User | None:
    """Look up an active user by email. Case-insensitive."""
    stmt = select(User).where(
        User.email == _normalize_email(email),
        User.is_active.is_(True),
    )
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def get_user(session: AsyncSession, user_id: UUID) -> User | None:
    """Return an active user by ID, or None."""
    stmt = select(User).where(User.id == user_id, User.is_active.is_(True))
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def create_user(session: AsyncSession, email: str) -> User:
    """Create a new dashboard user. Raises IntegrityError on duplicate email."""
    user = User(email=_normalize_email(email))
    session.add(user)
    await session.flush()
    return user


async def touch_last_login(session: AsyncSession, user_id: UUID) -> None:
    """Bump ``last_login_at`` to now for the given user."""
    stmt = update(User).where(User.id == user_id).values(last_login_at=func.now())
    await session.execute(stmt)
    await session.flush()


async def get_user_campaigns(session: AsyncSession, user_id: UUID) -> list[Campaign]:
    """Return every campaign a user can see on the dashboard.

    Union of:
    - campaigns explicitly granted via the ``user_campaigns`` join
      table (pre-Phase-D sharing model — kept for legacy operator
      access)
    - campaigns owned outright by the user (Phase D onwards, set
      when the user imports a campaign via the self-serve flow)

    Duplicates are collapsed; results are name-ordered.
    """
    shared_ids = select(UserCampaign.campaign_id).where(UserCampaign.user_id == user_id)
    stmt = (
        select(Campaign)
        .where((Campaign.id.in_(shared_ids)) | (Campaign.owner_user_id == user_id))
        .order_by(Campaign.name)
    )
    result = await session.execute(stmt)
    return list(result.scalars().unique().all())


async def count_active_campaigns_for_user(session: AsyncSession, user_id: UUID) -> int:
    """Count the *active* campaigns a user owns.

    Used to enforce ``settings.max_campaigns_per_user`` at import
    time. Only counts rows where ``is_active = TRUE`` — paused or
    retired campaigns don't eat into the cap, which lets users
    rotate through campaigns without hitting the ceiling forever.
    """
    stmt = (
        select(func.count())
        .select_from(Campaign)
        .where(
            Campaign.owner_user_id == user_id,
            Campaign.is_active.is_(True),
        )
    )
    result = await session.execute(stmt)
    return int(result.scalar_one() or 0)


async def list_campaigns_for_user(session: AsyncSession, user_id: UUID) -> list[Campaign]:
    """Return every campaign *owned* by the given user (not shared)."""
    stmt = select(Campaign).where(Campaign.owner_user_id == user_id).order_by(Campaign.name)
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def get_imported_meta_campaign_ids_for_user(session: AsyncSession, user_id: UUID) -> set[str]:
    """Return the set of ``platform_campaign_id`` values this user
    has already imported from Meta.

    The import picker uses this to grey out / filter out campaigns
    that would be a no-op duplicate.
    """
    stmt = select(Campaign.platform_campaign_id).where(
        Campaign.owner_user_id == user_id,
        Campaign.platform_campaign_id.is_not(None),
    )
    result = await session.execute(stmt)
    return {str(row) for row in result.scalars().all() if row}


async def grant_user_campaign_access(
    session: AsyncSession,
    user_id: UUID,
    campaign_id: UUID,
) -> UserCampaign:
    """Grant a user access to a campaign (idempotent).

    Uses an ``ON CONFLICT DO NOTHING`` upsert so re-running the CLI with
    an already-granted pair is a no-op. Returns the (existing or newly
    created) row.
    """
    stmt = (
        pg_insert(UserCampaign)
        .values(user_id=user_id, campaign_id=campaign_id)
        .on_conflict_do_nothing(index_elements=["user_id", "campaign_id"])
    )
    await session.execute(stmt)
    await session.flush()

    fetch = select(UserCampaign).where(
        UserCampaign.user_id == user_id,
        UserCampaign.campaign_id == campaign_id,
    )
    result = await session.execute(fetch)
    return result.scalar_one()


async def revoke_user_campaign_access(
    session: AsyncSession,
    user_id: UUID,
    campaign_id: UUID,
) -> bool:
    """Remove a user's access to a campaign. Returns False if it didn't exist."""
    stmt = select(UserCampaign).where(
        UserCampaign.user_id == user_id,
        UserCampaign.campaign_id == campaign_id,
    )
    result = await session.execute(stmt)
    row = result.scalar_one_or_none()
    if row is None:
        return False
    await session.delete(row)
    await session.flush()
    return True


async def delete_campaign_cascade(
    session: AsyncSession,
    campaign_id: UUID,
) -> bool:
    """Delete a campaign and every row transitively owned by it.

    Most FKs that point at ``campaigns.id`` (and at ``variants.id`` /
    ``test_cycles.id`` one hop away) are ``ON DELETE NO ACTION``, so a
    raw ``DELETE FROM campaigns`` fails with a FK violation. This
    helper walks the tables in leaf-to-root order inside one SQL
    transaction so the database returns to a consistent state whether
    the full cascade succeeds or any step fails.

    Returns ``True`` if the campaign was found and deleted, ``False``
    if no row matched (idempotent for callers that don't want to
    distinguish).

    Tables cleared (in order):
      1. ``cycle_actions`` — by variant or by test cycle
      2. ``metrics`` — by variant (TimescaleDB hypertable chunks
         cascade automatically)
      3. ``approval_queue`` — by variant or by campaign
      4. ``deployments`` — by variant
      5. ``test_cycles`` — by campaign
      6. ``variants`` — by campaign
      7. ``element_interactions`` — by campaign
      8. ``element_performance`` — by campaign
      9. ``media_assets`` — by campaign
     10. ``campaigns`` — the root row (``user_campaigns`` cascades and
         ``usage_log.campaign_id`` sets NULL automatically)

    Callers are still responsible for committing the session — this
    function only flushes.
    """
    # Existence check up-front so we can return the right boolean
    # without doing any destructive work.
    exists = await session.execute(
        select(Campaign.id).where(Campaign.id == campaign_id)
    )
    if exists.scalar_one_or_none() is None:
        return False

    # Collect the variant + test-cycle id lists once. Using
    # ``DELETE ... WHERE variant_id IN (SELECT ...)`` would work too
    # but pulling the ids up-front makes the individual statements
    # cheaper and easier to log if anything goes wrong mid-cascade.
    variant_ids_stmt = await session.execute(
        text("SELECT id FROM variants WHERE campaign_id = :cid"),
        {"cid": campaign_id},
    )
    variant_ids = [row[0] for row in variant_ids_stmt.fetchall()]

    cycle_ids_stmt = await session.execute(
        text("SELECT id FROM test_cycles WHERE campaign_id = :cid"),
        {"cid": campaign_id},
    )
    cycle_ids = [row[0] for row in cycle_ids_stmt.fetchall()]

    # Step 1: cycle_actions — remove anything keyed by either side.
    # Some rows may reference a test_cycle for this campaign, others
    # reference a variant for this campaign; deleting both keys
    # covers every valid combination.
    if cycle_ids:
        await session.execute(
            text("DELETE FROM cycle_actions WHERE cycle_id = ANY(:ids)"),
            {"ids": cycle_ids},
        )
    if variant_ids:
        await session.execute(
            text("DELETE FROM cycle_actions WHERE variant_id = ANY(:ids)"),
            {"ids": variant_ids},
        )

    if variant_ids:
        # Step 2: metrics (hypertable chunks auto-cascade).
        await session.execute(
            text("DELETE FROM metrics WHERE variant_id = ANY(:ids)"),
            {"ids": variant_ids},
        )
        # Step 3a: approval_queue rows keyed by variant.
        await session.execute(
            text("DELETE FROM approval_queue WHERE variant_id = ANY(:ids)"),
            {"ids": variant_ids},
        )
        # Step 4: deployments (variant-scoped).
        await session.execute(
            text("DELETE FROM deployments WHERE variant_id = ANY(:ids)"),
            {"ids": variant_ids},
        )

    # Step 3b: any approval_queue rows keyed by the campaign itself
    # (e.g. scale_budget proposals without a specific variant).
    await session.execute(
        text("DELETE FROM approval_queue WHERE campaign_id = :cid"),
        {"cid": campaign_id},
    )

    # Step 5: test_cycles (now that cycle_actions is gone).
    await session.execute(
        text("DELETE FROM test_cycles WHERE campaign_id = :cid"),
        {"cid": campaign_id},
    )

    # Step 6: variants (all dependents are gone).
    await session.execute(
        text("DELETE FROM variants WHERE campaign_id = :cid"),
        {"cid": campaign_id},
    )

    # Steps 7–9: campaign-scoped aggregates + media.
    for table in ("element_interactions", "element_performance", "media_assets"):
        await session.execute(
            text(f"DELETE FROM {table} WHERE campaign_id = :cid"),
            {"cid": campaign_id},
        )

    # Step 10: the root. ``user_campaigns`` cascades automatically;
    # ``usage_log.campaign_id`` nulls out per its SET NULL rule.
    await session.execute(
        text("DELETE FROM campaigns WHERE id = :cid"),
        {"cid": campaign_id},
    )

    await session.flush()
    return True


# ---------------------------------------------------------------------------
# Meta OAuth connections (Phase B)
# ---------------------------------------------------------------------------


async def upsert_meta_connection(
    session: AsyncSession,
    user_id: UUID,
    meta_user_id: str,
    encrypted_access_token: str,
    token_expires_at: datetime | None,
    scopes: list[str] | None,
    available_ad_accounts: list[dict] | None = None,
    available_pages: list[dict] | None = None,
    default_ad_account_id: str | None = None,
    default_page_id: str | None = None,
) -> UserMetaConnection:
    """Insert or replace the Meta connection for a user.

    Re-OAuth flow: a user can click "Connect Meta" again at any time
    and the new token overwrites the old. The ``on_conflict_do_update``
    upsert keys on ``user_id`` (PK).

    Phase G extended the signature to include the enumerated ad
    accounts / Pages and per-user defaults. Callers that only need to
    refresh the token (e.g. a future token-refresh job) can leave the
    new kwargs as ``None`` — they'll only be overwritten when a value
    is supplied explicitly. In that path we preserve existing JSONB
    contents by falling back to the current DB values via COALESCE.
    """
    insert_values: dict[str, object] = {
        "user_id": user_id,
        "meta_user_id": meta_user_id,
        "encrypted_access_token": encrypted_access_token,
        "token_expires_at": token_expires_at,
        "scopes": scopes,
        "last_refreshed_at": func.now(),
    }
    if available_ad_accounts is not None:
        insert_values["available_ad_accounts"] = available_ad_accounts
    if available_pages is not None:
        insert_values["available_pages"] = available_pages
    if default_ad_account_id is not None:
        insert_values["default_ad_account_id"] = default_ad_account_id
    if default_page_id is not None:
        insert_values["default_page_id"] = default_page_id

    update_values: dict[str, object] = {
        "meta_user_id": meta_user_id,
        "encrypted_access_token": encrypted_access_token,
        "token_expires_at": token_expires_at,
        "scopes": scopes,
        "last_refreshed_at": func.now(),
    }
    if available_ad_accounts is not None:
        update_values["available_ad_accounts"] = available_ad_accounts
    if available_pages is not None:
        update_values["available_pages"] = available_pages
    if default_ad_account_id is not None:
        update_values["default_ad_account_id"] = default_ad_account_id
    if default_page_id is not None:
        update_values["default_page_id"] = default_page_id

    stmt = (
        pg_insert(UserMetaConnection)
        .values(**insert_values)
        .on_conflict_do_update(
            index_elements=["user_id"],
            set_=update_values,
        )
        .returning(UserMetaConnection)
    )
    result = await session.execute(stmt)
    await session.flush()
    return result.scalar_one()


async def get_meta_connection(session: AsyncSession, user_id: UUID) -> UserMetaConnection | None:
    """Return the Meta connection row for a user, or None."""
    stmt = select(UserMetaConnection).where(UserMetaConnection.user_id == user_id)
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def delete_meta_connection(session: AsyncSession, user_id: UUID) -> bool:
    """Delete a user's Meta connection. Returns False if there was none."""
    stmt = select(UserMetaConnection).where(UserMetaConnection.user_id == user_id)
    result = await session.execute(stmt)
    row = result.scalar_one_or_none()
    if row is None:
        return False
    await session.delete(row)
    await session.flush()
    return True


async def delete_meta_connection_by_meta_user_id(
    session: AsyncSession, meta_user_id: str
) -> UUID | None:
    """Delete a Meta connection by the Meta-side user ID.

    Used by the deauthorization webhook when Meta tells us a user
    removed the app — we only know their Meta ID, not our internal
    user ID.

    Returns the internal ``user_id`` if a row was found and deleted,
    or None if no matching connection existed.
    """
    stmt = select(UserMetaConnection).where(UserMetaConnection.meta_user_id == meta_user_id)
    result = await session.execute(stmt)
    row = result.scalar_one_or_none()
    if row is None:
        return None
    user_id = row.user_id
    await session.delete(row)
    await session.flush()
    return user_id


async def create_data_deletion_request(
    session: AsyncSession,
    *,
    confirmation_code: str,
    meta_user_id: str,
    user_id: UUID | None,
) -> DataDeletionRequest:
    """Record a Meta data-deletion callback for audit + status page."""
    row = DataDeletionRequest(
        confirmation_code=confirmation_code,
        meta_user_id=meta_user_id,
        user_id=user_id,
        status="completed",
    )
    session.add(row)
    await session.flush()
    return row


async def get_data_deletion_request(
    session: AsyncSession, confirmation_code: str
) -> DataDeletionRequest | None:
    """Look up a data-deletion request by its confirmation code."""
    stmt = select(DataDeletionRequest).where(
        DataDeletionRequest.confirmation_code == confirmation_code
    )
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def get_campaign_owner_id(session: AsyncSession, campaign_id: UUID) -> UUID | None:
    """Return the ``owner_user_id`` for a campaign, or None.

    Used by :mod:`src.adapters.meta_factory` to route a cycle to the
    right user's Meta token. None means "no owner yet — legacy
    campaign, use the global-token fallback".
    """
    stmt = select(Campaign.owner_user_id).where(Campaign.id == campaign_id)
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


# ---------------------------------------------------------------------------
# Magic-link single-use enforcement
# ---------------------------------------------------------------------------


async def consume_magic_link_token(session: AsyncSession, token_hash: str) -> bool:
    """Atomically mark a magic-link token hash as consumed.

    Returns ``True`` if this is the *first* time the hash has been seen
    (the caller may proceed to sign the user in), ``False`` if the hash
    has already been consumed (the caller must reject the request as
    ``invalid_link``).

    The insert is ``ON CONFLICT DO NOTHING`` so concurrent verify
    requests for the same token race cleanly: whichever insert actually
    inserts wins, every other observer sees zero affected rows.
    """
    stmt = (
        pg_insert(MagicLinkConsumed)
        .values(token_hash=token_hash)
        .on_conflict_do_nothing(index_elements=["token_hash"])
    )
    result = await session.execute(stmt)
    await session.flush()
    # ``rowcount`` is 1 when the insert actually wrote a row, 0 on conflict.
    return (result.rowcount or 0) > 0
