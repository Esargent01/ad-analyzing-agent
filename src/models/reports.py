"""Report Pydantic models for cycle and weekly summaries."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from src.models.analysis import ElementInsight, InteractionInsight


class VariantSummary(BaseModel):
    """Full-funnel variant summary used inside reports."""

    model_config = ConfigDict(strict=True)

    variant_id: UUID
    variant_code: str
    status: str
    impressions: int
    clicks: int
    conversions: int
    spend: Decimal
    ctr: Decimal
    cpa: Decimal | None

    # Extended funnel metrics
    reach: int = 0
    video_views_3s: int = 0
    video_views_15s: int = 0
    thruplays: int = 0
    link_clicks: int = 0
    landing_page_views: int = 0
    add_to_carts: int = 0
    purchases: int = 0
    purchase_value: Decimal = Decimal("0")
    hook_rate: Decimal = Decimal("0")
    hold_rate: Decimal = Decimal("0")
    cost_per_purchase: Decimal | None = None
    roas: Decimal | None = None


class CycleAction(BaseModel):
    """A single action taken during a cycle, for audit logging."""

    model_config = ConfigDict(strict=True)

    action: str
    variant_id: UUID | None
    variant_code: str | None
    details: dict[str, str | int | float | bool | None]


class CycleReport(BaseModel):
    """Summary of a single optimization cycle."""

    model_config = ConfigDict(strict=True)

    campaign_id: UUID
    cycle_number: int
    started_at: datetime
    completed_at: datetime | None
    phase: str
    variants_active: int
    variants_launched: int
    variants_paused: int
    variants_promoted: int
    total_spend: Decimal
    avg_ctr: Decimal | None
    avg_cpa: Decimal | None
    variant_summaries: list[VariantSummary]
    actions_taken: list[CycleAction]
    summary_text: str
    error_log: str | None = None


class FunnelStage(BaseModel):
    """A single stage in the funnel comparison."""

    model_config = ConfigDict(strict=True)

    stage_name: str
    value: int
    rate: Decimal | None = None  # conversion rate from previous stage
    cost_per: Decimal | None = None  # cost per this event


class WeeklyReport(BaseModel):
    """Aggregated weekly report sent via email."""

    model_config = ConfigDict(strict=True)

    campaign_id: UUID
    campaign_name: str
    week_start: date
    week_end: date

    # Core aggregates
    total_spend: Decimal
    total_impressions: int
    total_clicks: int
    total_conversions: int
    avg_ctr: Decimal
    avg_cpa: Decimal | None

    # Extended funnel aggregates
    total_reach: int = 0
    total_video_views_3s: int = 0
    total_video_views_15s: int = 0
    total_thruplays: int = 0
    total_link_clicks: int = 0
    total_landing_page_views: int = 0
    total_add_to_carts: int = 0
    total_purchases: int = 0
    total_purchase_value: Decimal = Decimal("0")
    avg_hook_rate: Decimal = Decimal("0")
    avg_hold_rate: Decimal = Decimal("0")
    avg_cpm: Decimal = Decimal("0")
    avg_frequency: Decimal = Decimal("0")
    avg_roas: Decimal | None = None
    avg_cost_per_purchase: Decimal | None = None

    # Funnel stages for visualization
    funnel_stages: list[FunnelStage] = []

    # Variant data
    best_variant: VariantSummary | None
    worst_variant: VariantSummary | None
    all_variants: list[VariantSummary] = []

    # Element + interaction data
    top_elements: list[ElementInsight]
    top_interactions: list[InteractionInsight]

    # Activity counters
    cycles_run: int
    variants_launched: int
    variants_retired: int
    summary_text: str
