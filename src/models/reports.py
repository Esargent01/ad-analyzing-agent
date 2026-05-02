"""Report Pydantic models for cycle and weekly summaries."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from src.models.analysis import ElementInsight, InteractionInsight


# ---------------------------------------------------------------------------
# Display view-models for objective-aware rendering.
#
# Every objective-aware section (daily 4-up, weekly 3-row metric grid,
# best-variant spotlight summary + diagnostic tiles, variant-leaderboard
# columns) is pre-computed server-side into these shapes and shipped on
# the ``DailyReport`` / ``WeeklyReport`` response. Both the email
# templates and the React dashboard iterate the same structure so the
# rendering stays in lockstep across surfaces.
# ---------------------------------------------------------------------------


class HeadlineMetric(BaseModel):
    """One card in the top-line metric grid (daily 4-up / weekly 4-up rows).

    ``value`` and ``sub`` are pre-formatted strings; the renderer only
    decides layout + color tone. ``tone`` comes from the per-objective
    tone-direction spec (``up`` = higher-is-better → up-arrow is green,
    ``down`` = lower-is-better → down-arrow is green).
    """

    model_config = ConfigDict(strict=False)

    label: str
    value: str
    sub: str | None = None
    tone: Literal["good", "bad", "neutral"] = "neutral"


class SummaryNumber(BaseModel):
    """One of the 3 summary numbers in the best-variant spotlight header
    (e.g. CPA / ROAS / PURCH for a Sales campaign; CPL / CTR / LEADS
    for a Leads campaign)."""

    model_config = ConfigDict(strict=False)

    label: str
    value: str
    tone: Literal["good", "bad", "neutral"] = "neutral"


class DiagnosticTile(BaseModel):
    """One of the 3 diagnostic tiles under the spotlight card.

    Media-type aware: image creatives get one set, video/mixed/unknown
    get another (see ``src/services/objectives.py`` per-profile
    ``image_diagnostic_specs`` / ``video_diagnostic_specs``).
    """

    model_config = ConfigDict(strict=False)

    label: str
    value: str
    benchmark: str | None = None
    tone: Literal["good", "bad", "neutral"] = "neutral"


class VariantTableColumn(BaseModel):
    """One data column (between TYPE and STATUS) in the variant
    leaderboard table. ``key`` names the accessor on a VariantReport
    / VariantSummary; ``fmt`` tells the renderer how to stringify the
    raw value; ``image_em_dash`` when true prints ``—`` instead of the
    raw value on image-ad rows (the Hook-rate convention).
    """

    model_config = ConfigDict(strict=False)

    label: str
    key: str
    fmt: str
    image_em_dash: bool = False

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
    # Creative format: "video", "image", "mixed", or "unknown". Sourced
    # from ``variants.media_type`` (mapped from Meta's
    # ``AdCreative.object_type``). Renderers use this to hide
    # video-only metrics (hook rate, hold rate, 3s/15s views) on image
    # ads. "unknown" is treated identically to video/mixed — safe
    # default for rows that predate the column.
    media_type: str = "unknown"

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

    # Objective-specific counts + derived metrics. Zero defaults so
    # pre-PR-2 callers that don't set them still validate.
    leads: int = 0
    post_engagements: int = 0
    cost_per_lead: float | None = None  # None when leads == 0
    cost_per_engagement: float | None = None  # None when engagements == 0
    engagement_rate_pct: float = 0.0  # post_engagements / impressions * 100
    cpc: float | None = None  # None when link_clicks == 0
    cpm: float = 0.0  # spend / impressions * 1000


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

    # Campaign objective (canonical ODAX value). Drives every
    # objective-aware display list below. Defaults to Sales for
    # backwards compatibility with callers that don't populate it.
    objective: str = "OUTCOME_SALES"

    # Top-line aggregates (Sales-centric, kept for back-compat — the
    # objective-aware 4-up uses ``headline_metrics`` below).
    total_spend: Decimal
    total_purchases: int
    avg_cost_per_purchase: float | None
    avg_roas: float | None
    avg_hook_rate_pct: float

    # Additional aggregates that fuel non-Sales headline cards. Zero /
    # None defaults so pre-existing callers still validate.
    total_leads: int = 0
    total_post_engagements: int = 0
    total_impressions: int = 0
    total_reach: int = 0
    total_link_clicks: int = 0
    avg_cost_per_lead: float | None = None
    avg_cost_per_engagement: float | None = None
    avg_cpc: float | None = None
    avg_cpm: float = 0.0
    avg_ctr: float = 0.0

    # Vs previous day (sales-centric existing + new-metric prev fields
    # for objective-aware tone arrows).
    prev_spend: Decimal | None = None
    prev_purchases: int | None = None
    prev_avg_cpa: float | None = None
    prev_avg_roas: float | None = None
    prev_leads: int | None = None
    prev_post_engagements: int | None = None
    prev_link_clicks: int | None = None
    prev_impressions: int | None = None
    prev_reach: int | None = None
    prev_avg_cpl: float | None = None
    prev_avg_cpe: float | None = None
    prev_avg_cpc: float | None = None
    prev_avg_cpm: float | None = None
    prev_avg_ctr: float | None = None

    # All active variants sorted by the objective's ranker.
    variants: list[VariantReport]

    # Best ad — pick logic varies per objective (see
    # ``src/services/objectives.py::ObjectiveProfile.best_variant_ranker``).
    best_variant: VariantReport | None = None
    best_variant_funnel: list[ReportFunnelStage] = []
    best_variant_diagnostics: list[Diagnostic] = []
    best_variant_projection: str | None = None

    # --- Objective-aware display lists ---------------------------------
    # Pre-built server-side so both the Jinja email templates and the
    # React dashboard iterate the same shape.
    headline_metrics: list[HeadlineMetric] = []
    best_variant_summary: list[SummaryNumber] = []
    best_variant_diagnostic_tiles: list[DiagnosticTile] = []
    variant_table_columns: list[VariantTableColumn] = []

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

    # Loosened from strict=True to strict=False because the
    # objective-aware builder now populates Decimal-derived floats
    # (``cpc``, ``cpm``, ``cost_per_lead``, ``cost_per_engagement``)
    # whose dtype floats happen to be passed as Decimal by the
    # aggregation path. Both shapes are accepted.
    model_config = ConfigDict(strict=False)

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
    # Creative format mirrored from ``variants.media_type``. Weekly
    # templates read this the same way daily ones do — hide hook/hold
    # columns for image-only variants. Default "unknown" is treated as
    # video/mixed (full metrics) by the renderers.
    media_type: str = "unknown"

    # Objective-aware fields — populated by the weekly builder.
    leads: int = 0
    post_engagements: int = 0
    cost_per_lead: Decimal | None = None
    cost_per_engagement: Decimal | None = None
    cpc: Decimal | None = None
    cpm: Decimal = Decimal("0")
    frequency: Decimal = Decimal("0")
    # Rates (as 0-100 pct) so the variant table can render them
    # without re-deriving from raw counts.
    hook_rate_pct: float = 0.0
    hold_rate_pct: float = 0.0
    ctr_pct: float = 0.0


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


class WeeklyMetricRow(BaseModel):
    """One row of the weekly report's 3-row metric grid. Title is the
    mono eyebrow above the row; ``cards`` are 4 :class:`HeadlineMetric`."""

    model_config = ConfigDict(strict=False)

    title: str
    cards: list[HeadlineMetric] = []


class WeeklyReport(BaseModel):
    """Aggregated weekly report sent via email."""

    # Loosened from strict=True to strict=False to match DailyReport —
    # new derived float fields from objective-aware aggregation flow
    # through here too.
    model_config = ConfigDict(strict=False)

    campaign_id: UUID
    campaign_name: str
    week_start: date
    week_end: date

    # True when this report covers a week that hasn't fully elapsed yet
    # (week_end >= today UTC). The dashboard and email templates relabel
    # the report as "Current week" instead of presenting it as the
    # finalized weekly roll-up. KLEIBER-4.
    is_in_progress: bool = False

    # Canonical ODAX objective — drives the objective-aware display lists.
    objective: str = "OUTCOME_SALES"

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
    avg_cpc: Decimal = Decimal("0")
    avg_frequency: Decimal = Decimal("0")
    avg_roas: Decimal | None = None
    avg_cost_per_purchase: Decimal | None = None

    # Objective-aware aggregates
    total_leads: int = 0
    total_post_engagements: int = 0
    avg_cost_per_lead: Decimal | None = None
    avg_cost_per_engagement: Decimal | None = None
    lpv_rate_pct: float = 0.0  # landing_page_views / link_clicks * 100

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

    # --- Objective-aware display lists -------------------------------
    metric_rows: list[WeeklyMetricRow] = []
    best_variant_summary: list[SummaryNumber] = []
    best_variant_diagnostic_tiles: list[DiagnosticTile] = []
    variant_table_columns: list[VariantTableColumn] = []
