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
from datetime import datetime, timedelta, timezone
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
from src.models.analysis import ElementInsight, InteractionInsight
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
        logger.info(
            "Expired %d stale proposals for campaign %s", expired_count, campaign_id
        )

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
        text(
            "SELECT COUNT(*) FROM variants "
            "WHERE campaign_id = :id AND status = 'active'"
        ),
        {"id": campaign_id},
    )
    active_count = int(active_row.scalar_one())

    pending_row = await session.execute(
        text(
            "SELECT COUNT(*) FROM approval_queue "
            "WHERE campaign_id = :id AND approved IS NULL"
        ),
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
        text(
            "SELECT genome FROM variants "
            "WHERE campaign_id = :id AND status != 'retired'"
        ),
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
        text(
            "SELECT COALESCE(MAX(generation), 0) FROM variants WHERE campaign_id = :id"
        ),
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
            logger.warning(
                "Failed to queue weekly variant for genome %s: %s", result.genome, exc
            )

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
    """Load all pending proposed variants for a campaign, classified for the report.

    Classification:
    - "new": submitted within the last 7 days
    - "expiring_soon": submitted 7+ days ago (user has a week before auto-reject)
    """
    settings = get_settings()
    ttl_days = settings.proposal_ttl_days
    now = datetime.now(timezone.utc)
    expiring_threshold = now - timedelta(days=7)

    pending = await get_pending_approvals(session, campaign_id=campaign_id)

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
            submitted_at = submitted_at.replace(tzinfo=timezone.utc)

        age_days = (now - submitted_at).days
        classification = (
            "expiring_soon" if submitted_at < expiring_threshold else "new"
        )
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
