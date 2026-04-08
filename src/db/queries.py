"""Standalone async query functions for the ad creative agent system.

All functions accept an AsyncSession as the first argument and use
SQLAlchemy's select() construct. No raw SQL.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import Integer, func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.tables import (
    ActionType,
    ApprovalQueueItem,
    Campaign,
    CycleAction,
    Deployment,
    ElementInteraction,
    ElementPerformance,
    GenePoolEntry,
    Metric,
    TestCycle,
    Variant,
    VariantStatus,
)


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


async def submit_for_approval(
    session: AsyncSession,
    variant_id: UUID,
    campaign_id: UUID,
    genome: dict[str, str],
    hypothesis: str | None = None,
) -> ApprovalQueueItem:
    """Insert a variant into the approval queue for human review."""
    item = ApprovalQueueItem(
        variant_id=variant_id,
        campaign_id=campaign_id,
        genome_snapshot=genome,
        hypothesis=hypothesis,
    )
    session.add(item)
    await session.flush()
    return item


async def get_pending_approvals(
    session: AsyncSession,
    campaign_id: UUID | None = None,
) -> list[ApprovalQueueItem]:
    """Return approval queue items awaiting review (approved IS NULL)."""
    stmt = (
        select(ApprovalQueueItem)
        .where(ApprovalQueueItem.approved.is_(None))
        .order_by(ApprovalQueueItem.submitted_at)
    )
    if campaign_id is not None:
        stmt = stmt.where(ApprovalQueueItem.campaign_id == campaign_id)
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def approve_variant(
    session: AsyncSession,
    approval_id: UUID,
    reviewer: str = "cli",
) -> ApprovalQueueItem | None:
    """Approve a queued variant. Returns None if not found."""
    stmt = select(ApprovalQueueItem).where(ApprovalQueueItem.id == approval_id)
    result = await session.execute(stmt)
    item = result.scalar_one_or_none()
    if item is None:
        return None
    item.approved = True
    item.reviewed_at = func.now()
    item.reviewer = reviewer
    await session.flush()
    return item


async def reject_variant(
    session: AsyncSession,
    approval_id: UUID,
    reason: str,
    reviewer: str = "cli",
) -> ApprovalQueueItem | None:
    """Reject a queued variant and retire it. Returns None if not found."""
    stmt = select(ApprovalQueueItem).where(ApprovalQueueItem.id == approval_id)
    result = await session.execute(stmt)
    item = result.scalar_one_or_none()
    if item is None:
        return None
    item.approved = False
    item.reviewed_at = func.now()
    item.reviewer = reviewer
    item.rejection_reason = reason

    # Also retire the variant
    variant = await session.get(Variant, item.variant_id)
    if variant is not None:
        variant.status = VariantStatus.retired
        variant.retired_at = func.now()

    await session.flush()
    return item
