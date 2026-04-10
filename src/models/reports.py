"""Report Pydantic models for cycle and weekly summaries."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from src.models.analysis import ElementInsight, InteractionInsight

# ---------------------------------------------------------------------------
# New daily-report models (v2)
# ---------------------------------------------------------------------------


class VariantReport(BaseModel):
    """Per-variant data for the daily report."""

    model_config = ConfigDict(strict=False)  # Allow float/Decimal flexibility

    variant_id: UUID
    variant_code: str
    genome: dict[str, str]
    genome_summary: str  # e.g., "urgency headline + green CTA"
    hypothesis: str | None
    status: str  # "winner", "steady", "new", "fatigue", "paused"
    days_active: int

    # Primary
    spend: Decimal
    purchases: int
    purchase_value: Decimal
    cost_per_purchase: float | None  # None if 0 purchases
    roas: float | None

    # Diagnostic
    impressions: int
    reach: int
    video_views_3s: int
    video_views_15s: int
    link_clicks: int
    landing_page_views: int
    add_to_carts: int

    # Computed rates (0-100 scale)
    hook_rate_pct: float
    hold_rate_pct: float
    ctr_pct: float
    atc_rate_pct: float  # add_to_carts / link_clicks * 100
    checkout_rate_pct: float  # purchases / add_to_carts * 100
    frequency: float


class ReportFunnelStage(BaseModel):
    """Single stage in the funnel visualization."""

    model_config = ConfigDict(strict=False)

    label: str
    count: int
    rate_pct: float  # rate from previous stage
    rate_label: str  # e.g., "hook rate", "CTR"
    dropoff_pct: float  # % lost between previous stage and this one
    bar_color: str


class Diagnostic(BaseModel):
    """Single diagnostic observation."""

    model_config = ConfigDict(strict=False)

    text: str
    severity: str  # "good", "warning", "bad"


class FatigueAlert(BaseModel):
    """Fatigue warning for a variant."""

    model_config = ConfigDict(strict=False)

    variant_code: str
    reason: str
    recommendation: str


class ReportCycleAction(BaseModel):
    """Action taken by the system this cycle (for report display)."""

    model_config = ConfigDict(strict=False)

    action_type: str  # launch, pause, increase_budget, etc.
    variant_code: str
    details: str | None


class NextCyclePreview(BaseModel):
    """Planned action for next cycle."""

    model_config = ConfigDict(strict=False)

    hypothesis: str
    genome_summary: str


class DailyReport(BaseModel):
    """Complete daily report data for template rendering."""

    model_config = ConfigDict(strict=False)

    campaign_name: str
    campaign_id: UUID
    cycle_number: int
    report_date: date
    day_number: int  # day since campaign start

    # Top-line aggregates
    total_spend: Decimal
    total_purchases: int
    avg_cost_per_purchase: float | None
    avg_roas: float | None
    avg_hook_rate_pct: float

    # Vs previous day
    prev_spend: Decimal | None = None
    prev_purchases: int | None = None
    prev_avg_cpa: float | None = None
    prev_avg_roas: float | None = None

    # All active variants sorted by CPA
    variants: list[VariantReport]

    # Best ad (lowest CPA with >= 3 purchases)
    best_variant: VariantReport | None = None
    best_variant_funnel: list[ReportFunnelStage] = []
    best_variant_diagnostics: list[Diagnostic] = []
    best_variant_projection: str | None = None

    # Alerts and actions
    fatigue_alerts: list[FatigueAlert] = []
    actions: list[ReportCycleAction] = []
    next_cycle: list[NextCyclePreview] = []

    # Winners declared this cycle
    winners: list[VariantReport] = []


# ---------------------------------------------------------------------------
# Original models (kept for backward compatibility)
# ---------------------------------------------------------------------------


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


class ProposedVariant(BaseModel):
    """A variant queued for user approval, shown in the weekly report."""

    model_config = ConfigDict(strict=False)

    approval_id: UUID
    variant_id: UUID
    variant_code: str
    genome: dict[str, str]
    genome_summary: str  # e.g., "urgency headline + retargeting audience"
    hypothesis: str | None
    submitted_at: datetime
    classification: str  # "new" (this week) or "expiring_soon" (>7 days old)
    days_until_expiry: int  # for expiring_soon badges


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

    # Proposed variants awaiting user review (weekly feedback loop)
    proposed_variants: list[ProposedVariant] = []
    expired_count: int = 0  # proposals auto-rejected this week due to TTL
    generation_paused: bool = False  # True if queue at capacity
    review_url: str | None = None  # tokenized link to review page
