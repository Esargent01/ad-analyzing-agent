"""Analysis result Pydantic models."""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from src.models.variant import VariantStatus


class ElementInsight(BaseModel):
    """Performance summary for a single gene pool element."""

    model_config = ConfigDict(strict=True)

    slot_name: str
    slot_value: str
    variants_tested: int
    avg_ctr: Decimal
    avg_cpa: Decimal | None
    best_ctr: Decimal | None
    worst_ctr: Decimal | None
    total_impressions: int
    total_conversions: int
    confidence: Decimal | None

    # Extended funnel metrics
    avg_hook_rate: Decimal | None = None
    avg_roas: Decimal | None = None
    best_hook_rate: Decimal | None = None
    best_cpa: Decimal | None = None
    total_purchases: int = 0


class InteractionInsight(BaseModel):
    """Performance summary for a pair of gene pool elements."""

    model_config = ConfigDict(strict=True)

    slot_a_name: str
    slot_a_value: str
    slot_b_name: str
    slot_b_value: str
    variants_tested: int
    combined_avg_ctr: Decimal
    solo_a_avg_ctr: Decimal | None
    solo_b_avg_ctr: Decimal | None
    interaction_lift: Decimal | None
    confidence: Decimal | None


class VariantSignificanceResult(BaseModel):
    """Statistical significance result for a single variant vs. baseline."""

    model_config = ConfigDict(strict=True)

    variant_id: UUID
    variant_code: str
    ctr: Decimal
    baseline_ctr: Decimal
    p_value: float
    is_significant: bool
    recommended_action: VariantStatus


class AnalysisResult(BaseModel):
    """Full output of a single analysis cycle."""

    model_config = ConfigDict(strict=True)

    campaign_id: UUID
    cycle_number: int
    variant_results: list[VariantSignificanceResult]
    element_insights: list[ElementInsight]
    interaction_insights: list[InteractionInsight]
    fatigued_variants: list[UUID]
    summary: str
