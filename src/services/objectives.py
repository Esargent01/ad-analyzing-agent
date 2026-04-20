"""Per-objective dispatch for objective-aware reports.

This module is the single source of truth for **how** reports differ
per Meta campaign objective. Every render path that has been
sales-centric to date (Spend · Purchases · Avg. CPA · ROAS headline;
lowest-CPA best-variant pick; Hook/Hold/CTR diagnostic tiles) now
delegates here.

The design is deliberately data-heavy rather than code-heavy: each
objective is represented by an :class:`ObjectiveProfile` which
declares the metric keys to surface in each slot (top-line cards,
best-variant spotlight summary, variant-table columns, funnel
ordering, benchmarks). The small collection of builder functions at
the bottom turn a profile + a concrete ``VariantReport`` or totals
object into display-ready view models (``HeadlineMetric``,
``SummaryNumber``, ``DiagnosticTile``, ``VariantTableColumn``) which
live on the report response so both the email Jinja templates and
the React dashboard consume exactly the same shape.

Five of the six ODAX objectives are first-class here; App Promotion
falls through to the Sales default in v1 (see the planning doc —
App Promotion would need additional action-type parsing and likely
has zero current users). Unknown / deferred values also render as
Sales, with a ``display_label`` chip of "Unknown" that the dashboard
surfaces so it's obvious something's off.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from src.models.reports import (
    DiagnosticTile,
    HeadlineMetric,
    SummaryNumber,
    VariantReport,
    VariantTableColumn,
)


# ---------------------------------------------------------------------------
# Format codes
# ---------------------------------------------------------------------------
# The report renderer (email.py Jinja filters + React formatters)
# interprets these as the canonical way to render each metric. Keep
# the set small; every new format means adding a case in two places.


class Fmt:
    CURRENCY = "currency"  # "$12.34" (<1000) / "$1,234" (>=1000)
    INT = "int"  # "12345" (no commas)
    INT_COMMA = "int_comma"  # "12,345"
    PCT = "pct"  # "2.3%"  (value is already 0-100)
    ROAS = "roas"  # "2.4x"
    ONE_DECIMAL = "onedecimal"  # "12.3"


# ---------------------------------------------------------------------------
# Benchmarks
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Benchmarks:
    """Per-objective benchmark thresholds. ``None`` means "not
    meaningful for this objective" — downstream display paths render
    the tile without a benchmark line or skip the tint logic.
    """

    # Engagement thresholds (pct)
    ctr_pct: float = 1.5
    hook_pct: float = 30.0
    hold_pct: float = 25.0
    atc_pct: float = 5.0
    checkout_pct: float = 30.0

    # Cost targets (USD)
    cpa_usd: float | None = 30.0
    cpl_usd: float | None = None
    cpc_usd: float | None = None
    cpm_usd: float | None = None
    cpe_usd: float | None = None


# Default benchmarks are the Sales-flavour ones that the current
# report already assumes. Per-objective profiles override the subset
# that matters.
_DEFAULT_BENCHMARKS = Benchmarks()


# ---------------------------------------------------------------------------
# Metric key specs
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class HeadlineSpec:
    """Specification for one headline metric card (daily 4-up or
    weekly 4-up row)."""

    label: str
    value_key: str  # attr on the totals object (DailyReport / WeeklyReport)
    fmt: str
    prev_key: str | None = None  # for the day-over-day delta arrow
    tone_direction: str = "neutral"  # "up" = higher-is-better, "down" = lower-is-better
    sub_when_empty: str | None = None  # fallback sub-line when value is zero/null


@dataclass(frozen=True)
class SummarySpec:
    """Specification for one of the 3 spotlight-header summary numbers."""

    label: str
    value_key: str  # attr on VariantReport / VariantSummary
    fmt: str
    tone: str = "neutral"  # "good" tints green; "bad" tints red


@dataclass(frozen=True)
class DiagnosticSpec:
    """Specification for one of the 3 diagnostic tiles under the
    spotlight card. Media-type aware: video / mixed / unknown uses the
    ``video`` list; image campaigns use the ``image`` list.
    """

    label: str
    value_key: str
    fmt: str
    benchmark_text: str | None = None
    good_threshold: float | None = None  # value ≥ this tints green


@dataclass(frozen=True)
class VariantColSpec:
    """Specification for one column in the "other variants" table."""

    label: str
    value_key: str
    fmt: str
    image_em_dash: bool = False  # image variants render "—" instead of value


# ---------------------------------------------------------------------------
# Best-variant rankers
# ---------------------------------------------------------------------------
# Each returns either the winning VariantReport or None if no variant
# qualifies for this objective yet (e.g. zero leads on a Leads
# campaign → no winner).


def _min_attr_ranker(
    attr: str,
    *,
    require_positive_spend: bool = True,
) -> Callable[[Sequence[VariantReport]], VariantReport | None]:
    """Rank by lowest positive value of ``attr``. Used for cost metrics
    (lowest-CPA, lowest-CPL, lowest-CPC, lowest-CPM)."""

    def _rank(variants: Sequence[VariantReport]) -> VariantReport | None:
        candidates = [
            v
            for v in variants
            if getattr(v, attr, None) is not None
            and float(getattr(v, attr)) > 0
            and (not require_positive_spend or float(v.spend) > 0)
        ]
        if not candidates:
            return None
        return min(candidates, key=lambda v: float(getattr(v, attr)))

    return _rank


def _max_attr_ranker(attr: str) -> Callable[[Sequence[VariantReport]], VariantReport | None]:
    """Rank by highest value of ``attr``. Used for volume metrics
    (most engagements, most reach)."""

    def _rank(variants: Sequence[VariantReport]) -> VariantReport | None:
        candidates = [v for v in variants if getattr(v, attr, None) is not None]
        if not candidates:
            return None
        best = max(candidates, key=lambda v: float(getattr(v, attr) or 0))
        # Returning a variant with zero of the metric is worse than
        # returning None — callers expect a "winner" to actually have
        # performed on the headline metric.
        if float(getattr(best, attr) or 0) <= 0:
            return None
        return best

    return _rank


# ---------------------------------------------------------------------------
# Objective profiles
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ObjectiveProfile:
    canonical: str
    display_label: str

    # Daily top-line: 4 HeadlineSpec cards.
    daily_headline_specs: tuple[HeadlineSpec, ...]

    # Weekly is organised into three rows of 4 cards each. Row titles
    # are the eyebrow labels above each row.
    weekly_row_titles: tuple[str, str, str]
    weekly_row_specs: tuple[
        tuple[HeadlineSpec, ...],
        tuple[HeadlineSpec, ...],
        tuple[HeadlineSpec, ...],
    ]

    # Spotlight header summary numbers (right side of the best-variant
    # card header) — 3 of them.
    summary_specs: tuple[SummarySpec, SummarySpec, SummarySpec]

    # Diagnostic tile row under the spotlight (media-type aware).
    image_diagnostic_specs: tuple[DiagnosticSpec, DiagnosticSpec, DiagnosticSpec]
    video_diagnostic_specs: tuple[DiagnosticSpec, DiagnosticSpec, DiagnosticSpec]

    # Variant-leaderboard columns between TYPE and STATUS.
    variant_col_specs: tuple[VariantColSpec, ...]

    # Funnel stage names in order — the report builder already knows
    # how to compose a ReportFunnelStage for each. Stopping before
    # ``purchases`` on a non-Sales objective is the point.
    funnel_stage_keys: tuple[str, ...]

    best_variant_ranker: Callable[[Sequence[VariantReport]], VariantReport | None]
    benchmarks: Benchmarks


# --- Shared image/video diagnostic sets -------------------------------------
# All objectives share the same video diagnostics today (Hook · Hold · CTR)
# and image campaigns always get CTR first. Only Awareness breaks the
# pattern.

_VIDEO_CREATIVE_DIAGNOSTICS = (
    DiagnosticSpec(
        label="HOOK",
        value_key="hook_rate_pct",
        fmt=Fmt.PCT,
        benchmark_text="benchmark 30%",
        good_threshold=30.0,
    ),
    DiagnosticSpec(
        label="HOLD",
        value_key="hold_rate_pct",
        fmt=Fmt.PCT,
        benchmark_text="benchmark 25%",
        good_threshold=25.0,
    ),
    DiagnosticSpec(
        label="CTR",
        value_key="ctr_pct",
        fmt=Fmt.PCT,
        benchmark_text="benchmark 1.5%",
        good_threshold=1.5,
    ),
)


_SALES_IMAGE_DIAGNOSTICS = (
    DiagnosticSpec(
        label="CTR",
        value_key="ctr_pct",
        fmt=Fmt.PCT,
        benchmark_text="benchmark 1.5%",
        good_threshold=1.5,
    ),
    DiagnosticSpec(
        label="ATC RATE",
        value_key="atc_rate_pct",
        fmt=Fmt.PCT,
        benchmark_text="benchmark 5\u201310%",
        good_threshold=5.0,
    ),
    DiagnosticSpec(
        label="CHECKOUT",
        value_key="checkout_rate_pct",
        fmt=Fmt.PCT,
        benchmark_text="benchmark 30%",
        good_threshold=30.0,
    ),
)


_NON_SALES_IMAGE_DIAGNOSTICS = (
    DiagnosticSpec(
        label="CTR",
        value_key="ctr_pct",
        fmt=Fmt.PCT,
        benchmark_text="benchmark 1.5%",
        good_threshold=1.5,
    ),
    DiagnosticSpec(
        label="FREQ",
        value_key="frequency",
        fmt=Fmt.ONE_DECIMAL,
        benchmark_text="sweet spot 1\u20133x",
        good_threshold=None,
    ),
    DiagnosticSpec(
        label="CPM",
        value_key="cpm",
        fmt=Fmt.CURRENCY,
        benchmark_text=None,
        good_threshold=None,
    ),
)


# --- Sales ------------------------------------------------------------------

_SALES = ObjectiveProfile(
    canonical="OUTCOME_SALES",
    display_label="Sales",
    daily_headline_specs=(
        HeadlineSpec("SPEND", "total_spend", Fmt.CURRENCY, "prev_spend", "neutral"),
        HeadlineSpec("PURCHASES", "total_purchases", Fmt.INT_COMMA, "prev_purchases", "up"),
        HeadlineSpec("AVG CPA", "avg_cost_per_purchase", Fmt.CURRENCY, "prev_avg_cpa", "down", "no purchases"),
        HeadlineSpec("AVG ROAS", "avg_roas", Fmt.ROAS, "prev_avg_roas", "up", "no purchases"),
    ),
    weekly_row_titles=("PURCHASES", "ENGAGEMENT", "VOLUME"),
    weekly_row_specs=(
        (
            HeadlineSpec("SPEND", "total_spend", Fmt.CURRENCY),
            HeadlineSpec("PURCHASES", "total_purchases", Fmt.INT_COMMA),
            HeadlineSpec("AVG CPA", "avg_cost_per_purchase", Fmt.CURRENCY),
            HeadlineSpec("AVG ROAS", "avg_roas", Fmt.ROAS),
        ),
        (
            HeadlineSpec("HOOK", "avg_hook_rate", Fmt.PCT),
            HeadlineSpec("HOLD", "avg_hold_rate", Fmt.PCT),
            HeadlineSpec("CTR", "avg_ctr", Fmt.PCT),
            HeadlineSpec("CPM", "avg_cpm", Fmt.CURRENCY),
        ),
        (
            HeadlineSpec("IMPRESSIONS", "total_impressions", Fmt.INT_COMMA),
            HeadlineSpec("REACH", "total_reach", Fmt.INT_COMMA),
            HeadlineSpec("REVENUE", "total_purchase_value", Fmt.CURRENCY),
            HeadlineSpec("FREQUENCY", "avg_frequency", Fmt.ONE_DECIMAL),
        ),
    ),
    summary_specs=(
        SummarySpec("CPA", "cost_per_purchase", Fmt.CURRENCY, "neutral"),
        SummarySpec("ROAS", "roas", Fmt.ROAS, "good"),
        SummarySpec("PURCH", "purchases", Fmt.INT_COMMA, "neutral"),
    ),
    image_diagnostic_specs=_SALES_IMAGE_DIAGNOSTICS,
    video_diagnostic_specs=_VIDEO_CREATIVE_DIAGNOSTICS,
    variant_col_specs=(
        VariantColSpec("HOOK", "hook_rate_pct", Fmt.PCT, image_em_dash=True),
        VariantColSpec("CTR", "ctr_pct", Fmt.PCT),
        VariantColSpec("CPA", "cost_per_purchase", Fmt.CURRENCY),
        VariantColSpec("ROAS", "roas", Fmt.ROAS),
    ),
    funnel_stage_keys=(
        "impressions",
        "video_views_3s",
        "video_views_15s",
        "link_clicks",
        "add_to_carts",
        "purchases",
    ),
    best_variant_ranker=_min_attr_ranker("cost_per_purchase"),
    benchmarks=Benchmarks(cpa_usd=30.0),
)


# --- Leads ------------------------------------------------------------------

_LEADS = ObjectiveProfile(
    canonical="OUTCOME_LEADS",
    display_label="Leads",
    daily_headline_specs=(
        HeadlineSpec("SPEND", "total_spend", Fmt.CURRENCY, "prev_spend", "neutral"),
        HeadlineSpec("LEADS", "total_leads", Fmt.INT_COMMA, "prev_leads", "up"),
        HeadlineSpec("AVG CPL", "avg_cost_per_lead", Fmt.CURRENCY, "prev_avg_cpl", "down", "no leads"),
        HeadlineSpec("CTR", "avg_ctr", Fmt.PCT, "prev_avg_ctr", "up"),
    ),
    weekly_row_titles=("LEADS", "ENGAGEMENT", "VOLUME"),
    weekly_row_specs=(
        (
            HeadlineSpec("SPEND", "total_spend", Fmt.CURRENCY),
            HeadlineSpec("LEADS", "total_leads", Fmt.INT_COMMA),
            HeadlineSpec("AVG CPL", "avg_cost_per_lead", Fmt.CURRENCY),
            HeadlineSpec("CTR", "avg_ctr", Fmt.PCT),
        ),
        (
            HeadlineSpec("HOOK", "avg_hook_rate", Fmt.PCT),
            HeadlineSpec("HOLD", "avg_hold_rate", Fmt.PCT),
            HeadlineSpec("CPC", "avg_cpc", Fmt.CURRENCY),
            HeadlineSpec("CPM", "avg_cpm", Fmt.CURRENCY),
        ),
        (
            HeadlineSpec("IMPRESSIONS", "total_impressions", Fmt.INT_COMMA),
            HeadlineSpec("REACH", "total_reach", Fmt.INT_COMMA),
            HeadlineSpec("LINK CLICKS", "total_link_clicks", Fmt.INT_COMMA),
            HeadlineSpec("FREQUENCY", "avg_frequency", Fmt.ONE_DECIMAL),
        ),
    ),
    summary_specs=(
        SummarySpec("CPL", "cost_per_lead", Fmt.CURRENCY, "neutral"),
        SummarySpec("CTR", "ctr_pct", Fmt.PCT, "good"),
        SummarySpec("LEADS", "leads", Fmt.INT_COMMA, "neutral"),
    ),
    image_diagnostic_specs=_NON_SALES_IMAGE_DIAGNOSTICS,
    video_diagnostic_specs=_VIDEO_CREATIVE_DIAGNOSTICS,
    variant_col_specs=(
        VariantColSpec("HOOK", "hook_rate_pct", Fmt.PCT, image_em_dash=True),
        VariantColSpec("CTR", "ctr_pct", Fmt.PCT),
        VariantColSpec("CPL", "cost_per_lead", Fmt.CURRENCY),
        VariantColSpec("LEADS", "leads", Fmt.INT_COMMA),
    ),
    funnel_stage_keys=(
        "impressions",
        "video_views_3s",
        "video_views_15s",
        "link_clicks",
        "leads",
    ),
    best_variant_ranker=_min_attr_ranker("cost_per_lead"),
    benchmarks=Benchmarks(cpl_usd=28.0, ctr_pct=2.6),
)


# --- Engagement -------------------------------------------------------------

_ENGAGEMENT = ObjectiveProfile(
    canonical="OUTCOME_ENGAGEMENT",
    display_label="Engagement",
    daily_headline_specs=(
        HeadlineSpec("SPEND", "total_spend", Fmt.CURRENCY, "prev_spend", "neutral"),
        HeadlineSpec("ENGAGEMENTS", "total_post_engagements", Fmt.INT_COMMA, "prev_post_engagements", "up"),
        HeadlineSpec("AVG CPE", "avg_cost_per_engagement", Fmt.CURRENCY, "prev_avg_cpe", "down", "no engagements"),
        HeadlineSpec("CTR", "avg_ctr", Fmt.PCT, "prev_avg_ctr", "up"),
    ),
    weekly_row_titles=("ENGAGEMENT", "CREATIVE", "VOLUME"),
    weekly_row_specs=(
        (
            HeadlineSpec("SPEND", "total_spend", Fmt.CURRENCY),
            HeadlineSpec("ENGAGEMENTS", "total_post_engagements", Fmt.INT_COMMA),
            HeadlineSpec("AVG CPE", "avg_cost_per_engagement", Fmt.CURRENCY),
            HeadlineSpec("CTR", "avg_ctr", Fmt.PCT),
        ),
        (
            HeadlineSpec("HOOK", "avg_hook_rate", Fmt.PCT),
            HeadlineSpec("HOLD", "avg_hold_rate", Fmt.PCT),
            HeadlineSpec("CPM", "avg_cpm", Fmt.CURRENCY),
            HeadlineSpec("FREQUENCY", "avg_frequency", Fmt.ONE_DECIMAL),
        ),
        (
            HeadlineSpec("IMPRESSIONS", "total_impressions", Fmt.INT_COMMA),
            HeadlineSpec("REACH", "total_reach", Fmt.INT_COMMA),
            HeadlineSpec("LINK CLICKS", "total_link_clicks", Fmt.INT_COMMA),
            HeadlineSpec("CPC", "avg_cpc", Fmt.CURRENCY),
        ),
    ),
    summary_specs=(
        SummarySpec("CPE", "cost_per_engagement", Fmt.CURRENCY, "neutral"),
        SummarySpec("CTR", "ctr_pct", Fmt.PCT, "good"),
        SummarySpec("ENGAGE", "post_engagements", Fmt.INT_COMMA, "neutral"),
    ),
    image_diagnostic_specs=_NON_SALES_IMAGE_DIAGNOSTICS,
    video_diagnostic_specs=_VIDEO_CREATIVE_DIAGNOSTICS,
    variant_col_specs=(
        VariantColSpec("HOOK", "hook_rate_pct", Fmt.PCT, image_em_dash=True),
        VariantColSpec("CTR", "ctr_pct", Fmt.PCT),
        VariantColSpec("CPE", "cost_per_engagement", Fmt.CURRENCY),
        VariantColSpec("ENGAGE", "post_engagements", Fmt.INT_COMMA),
    ),
    funnel_stage_keys=(
        "impressions",
        "video_views_3s",
        "video_views_15s",
        "post_engagements",
    ),
    best_variant_ranker=_max_attr_ranker("post_engagements"),
    benchmarks=Benchmarks(cpe_usd=0.20, ctr_pct=1.4),
)


# --- Traffic ----------------------------------------------------------------

_TRAFFIC = ObjectiveProfile(
    canonical="OUTCOME_TRAFFIC",
    display_label="Traffic",
    daily_headline_specs=(
        HeadlineSpec("SPEND", "total_spend", Fmt.CURRENCY, "prev_spend", "neutral"),
        HeadlineSpec("LINK CLICKS", "total_link_clicks", Fmt.INT_COMMA, "prev_link_clicks", "up"),
        HeadlineSpec("AVG CPC", "avg_cpc", Fmt.CURRENCY, "prev_avg_cpc", "down", "no clicks"),
        HeadlineSpec("CTR", "avg_ctr", Fmt.PCT, "prev_avg_ctr", "up"),
    ),
    weekly_row_titles=("TRAFFIC", "CREATIVE", "VOLUME"),
    weekly_row_specs=(
        (
            HeadlineSpec("SPEND", "total_spend", Fmt.CURRENCY),
            HeadlineSpec("LINK CLICKS", "total_link_clicks", Fmt.INT_COMMA),
            HeadlineSpec("AVG CPC", "avg_cpc", Fmt.CURRENCY),
            HeadlineSpec("CTR", "avg_ctr", Fmt.PCT),
        ),
        (
            HeadlineSpec("HOOK", "avg_hook_rate", Fmt.PCT),
            HeadlineSpec("HOLD", "avg_hold_rate", Fmt.PCT),
            HeadlineSpec("CPM", "avg_cpm", Fmt.CURRENCY),
            HeadlineSpec("FREQUENCY", "avg_frequency", Fmt.ONE_DECIMAL),
        ),
        (
            HeadlineSpec("IMPRESSIONS", "total_impressions", Fmt.INT_COMMA),
            HeadlineSpec("REACH", "total_reach", Fmt.INT_COMMA),
            HeadlineSpec("LPV", "total_landing_page_views", Fmt.INT_COMMA),
            HeadlineSpec("LPV RATE", "lpv_rate_pct", Fmt.PCT),
        ),
    ),
    summary_specs=(
        SummarySpec("CPC", "cpc", Fmt.CURRENCY, "neutral"),
        SummarySpec("LPV", "landing_page_views", Fmt.INT_COMMA, "neutral"),
        SummarySpec("CTR", "ctr_pct", Fmt.PCT, "good"),
    ),
    image_diagnostic_specs=_NON_SALES_IMAGE_DIAGNOSTICS,
    video_diagnostic_specs=_VIDEO_CREATIVE_DIAGNOSTICS,
    variant_col_specs=(
        VariantColSpec("HOOK", "hook_rate_pct", Fmt.PCT, image_em_dash=True),
        VariantColSpec("CTR", "ctr_pct", Fmt.PCT),
        VariantColSpec("CPC", "cpc", Fmt.CURRENCY),
        VariantColSpec("LPV", "landing_page_views", Fmt.INT_COMMA),
    ),
    funnel_stage_keys=(
        "impressions",
        "video_views_3s",
        "video_views_15s",
        "link_clicks",
        "landing_page_views",
    ),
    best_variant_ranker=_min_attr_ranker("cpc"),
    benchmarks=Benchmarks(cpc_usd=0.70, ctr_pct=2.0),
)


# --- Awareness --------------------------------------------------------------

_AWARENESS = ObjectiveProfile(
    canonical="OUTCOME_AWARENESS",
    display_label="Awareness",
    daily_headline_specs=(
        HeadlineSpec("SPEND", "total_spend", Fmt.CURRENCY, "prev_spend", "neutral"),
        HeadlineSpec("IMPRESSIONS", "total_impressions", Fmt.INT_COMMA, "prev_impressions", "up"),
        HeadlineSpec("REACH", "total_reach", Fmt.INT_COMMA, "prev_reach", "up"),
        HeadlineSpec("CPM", "avg_cpm", Fmt.CURRENCY, "prev_avg_cpm", "down"),
    ),
    weekly_row_titles=("AWARENESS", "CREATIVE", "VOLUME"),
    weekly_row_specs=(
        (
            HeadlineSpec("SPEND", "total_spend", Fmt.CURRENCY),
            HeadlineSpec("IMPRESSIONS", "total_impressions", Fmt.INT_COMMA),
            HeadlineSpec("REACH", "total_reach", Fmt.INT_COMMA),
            HeadlineSpec("CPM", "avg_cpm", Fmt.CURRENCY),
        ),
        (
            HeadlineSpec("HOOK", "avg_hook_rate", Fmt.PCT),
            HeadlineSpec("HOLD", "avg_hold_rate", Fmt.PCT),
            HeadlineSpec("CTR", "avg_ctr", Fmt.PCT),
            HeadlineSpec("FREQUENCY", "avg_frequency", Fmt.ONE_DECIMAL),
        ),
        (
            HeadlineSpec("SPEND", "total_spend", Fmt.CURRENCY),
            HeadlineSpec("LINK CLICKS", "total_link_clicks", Fmt.INT_COMMA),
            HeadlineSpec("CPC", "avg_cpc", Fmt.CURRENCY),
            HeadlineSpec("CPM", "avg_cpm", Fmt.CURRENCY),
        ),
    ),
    summary_specs=(
        SummarySpec("CPM", "cpm", Fmt.CURRENCY, "neutral"),
        SummarySpec("REACH", "reach", Fmt.INT_COMMA, "neutral"),
        SummarySpec("FREQ", "frequency", Fmt.ONE_DECIMAL, "good"),
    ),
    image_diagnostic_specs=_NON_SALES_IMAGE_DIAGNOSTICS,
    video_diagnostic_specs=_VIDEO_CREATIVE_DIAGNOSTICS,
    variant_col_specs=(
        VariantColSpec("CTR", "ctr_pct", Fmt.PCT),
        VariantColSpec("CPM", "cpm", Fmt.CURRENCY),
        VariantColSpec("FREQ", "frequency", Fmt.ONE_DECIMAL),
        VariantColSpec("REACH", "reach", Fmt.INT_COMMA),
    ),
    funnel_stage_keys=(
        "impressions",
        "reach",
    ),
    best_variant_ranker=_min_attr_ranker("cpm"),
    benchmarks=Benchmarks(cpm_usd=12.0, ctr_pct=0.8),
)


# ---------------------------------------------------------------------------
# Registry + lookup
# ---------------------------------------------------------------------------

OBJECTIVES: dict[str, ObjectiveProfile] = {
    "OUTCOME_SALES": _SALES,
    "OUTCOME_LEADS": _LEADS,
    "OUTCOME_ENGAGEMENT": _ENGAGEMENT,
    "OUTCOME_TRAFFIC": _TRAFFIC,
    "OUTCOME_AWARENESS": _AWARENESS,
}


def profile_for(objective: str | None) -> ObjectiveProfile:
    """Return the profile matching ``objective``. ``None`` / unknown /
    ``OUTCOME_APP_PROMOTION`` (deferred) / ``OUTCOME_UNKNOWN`` all fall
    back to Sales — the safest rendering because every metric Sales
    needs has always been collected. Upstream code is expected to
    surface the raw objective string separately so the UI can
    display an "unsupported" chip for the fallback cases.
    """
    if not objective:
        return _SALES
    return OBJECTIVES.get(objective, _SALES)


# ---------------------------------------------------------------------------
# Formatters
# ---------------------------------------------------------------------------
# Keep the set aligned with the Jinja filters registered in
# src/reports/email.py (currency, int_comma, pct, onedecimal) and with
# the React formatter in frontend/src/lib/format.ts. If a new code is
# added, update both places.


def format_value(value: Any, fmt: str) -> str:
    if value is None:
        return "—"
    try:
        v = float(value)
    except (TypeError, ValueError):
        return "—"

    if fmt == Fmt.CURRENCY:
        if v >= 1000:
            return f"${v:,.0f}"
        return f"${v:.2f}"
    if fmt == Fmt.INT:
        return f"{int(v)}"
    if fmt == Fmt.INT_COMMA:
        return f"{int(v):,}"
    if fmt == Fmt.PCT:
        return f"{v:.1f}%"
    if fmt == Fmt.ROAS:
        if v <= 0:
            return "N/A"
        return f"{v:.1f}x"
    if fmt == Fmt.ONE_DECIMAL:
        return f"{v:.1f}"
    return str(value)


# ---------------------------------------------------------------------------
# Display-list builders
# ---------------------------------------------------------------------------


def _get(obj: Any, key: str) -> Any:
    """Read ``key`` off either an attr-ful object or a dict."""
    if isinstance(obj, dict):
        return obj.get(key)
    return getattr(obj, key, None)


def _tone_for_delta(direction: str, current: float | None, previous: float | None) -> str:
    """Map ``direction`` ("up"=higher-is-better / "down"=lower-is-better /
    "neutral"=no tint) and numeric deltas into a ``good|bad|neutral``
    tone used by the renderer to pick a color.
    """
    if direction == "neutral" or current is None or previous is None:
        return "neutral"
    try:
        c, p = float(current), float(previous)
    except (TypeError, ValueError):
        return "neutral"
    if c == p:
        return "neutral"
    if direction == "up":
        return "good" if c > p else "bad"
    if direction == "down":
        return "good" if c < p else "bad"
    return "neutral"


def _delta_string(current: Any, previous: Any) -> str | None:
    """Render a short delta like ``↑ 12.3%`` vs. the previous period.
    Returns ``None`` when the delta isn't computable."""
    if current is None or previous is None:
        return None
    try:
        c, p = float(current), float(previous)
    except (TypeError, ValueError):
        return None
    if p == 0:
        # Going from zero to positive — show the absolute jump, not
        # an infinite percent.
        if c == 0:
            return "→ flat"
        if c > 0:
            return f"↑ +{int(c)} from 0"
        return f"↓ {int(c)} from 0"
    delta = ((c - p) / p) * 100
    arrow = "↑" if delta > 0.05 else "↓" if delta < -0.05 else "→"
    return f"{arrow} {abs(delta):.1f}%"


def build_headline_metrics(
    specs: Sequence[HeadlineSpec],
    report_or_totals: Any,
) -> list[HeadlineMetric]:
    """Build a list of :class:`HeadlineMetric` view models from a
    sequence of :class:`HeadlineSpec` + the report/totals object.

    Used by both the daily top-line 4-up and every weekly metric row.
    """
    out: list[HeadlineMetric] = []
    for spec in specs:
        value = _get(report_or_totals, spec.value_key)
        previous = _get(report_or_totals, spec.prev_key) if spec.prev_key else None
        delta = _delta_string(value, previous) if spec.prev_key else None

        # Pick a sub-line: delta when we have one, otherwise
        # sub_when_empty when the value is missing/zero.
        sub: str | None = delta
        if sub is None:
            try:
                num = float(value) if value is not None else 0.0
            except (TypeError, ValueError):
                num = 0.0
            if num == 0 and spec.sub_when_empty:
                sub = spec.sub_when_empty

        out.append(
            HeadlineMetric(
                label=spec.label,
                value=format_value(value, spec.fmt),
                sub=sub,
                tone=_tone_for_delta(spec.tone_direction, value, previous),
            )
        )
    return out


def build_summary_numbers(
    specs: Sequence[SummarySpec],
    variant: Any,
) -> list[SummaryNumber]:
    out: list[SummaryNumber] = []
    for spec in specs:
        value = _get(variant, spec.value_key)
        tone = spec.tone
        # Static-tone logic: "good" tint only applies when the value
        # is a non-zero positive number. Avoids painting a zero-
        # purchases "PURCH 0" box green.
        if tone == "good":
            try:
                if value is None or float(value) <= 0:
                    tone = "neutral"
            except (TypeError, ValueError):
                tone = "neutral"
        out.append(
            SummaryNumber(
                label=spec.label,
                value=format_value(value, spec.fmt),
                tone=tone,
            )
        )
    return out


def build_diagnostic_tiles(
    specs: Sequence[DiagnosticSpec],
    variant: Any,
) -> list[DiagnosticTile]:
    out: list[DiagnosticTile] = []
    for spec in specs:
        value = _get(variant, spec.value_key)
        tone = "neutral"
        if spec.good_threshold is not None and value is not None:
            try:
                if float(value) >= spec.good_threshold:
                    tone = "good"
            except (TypeError, ValueError):
                pass
        out.append(
            DiagnosticTile(
                label=spec.label,
                value=format_value(value, spec.fmt),
                benchmark=spec.benchmark_text,
                tone=tone,
            )
        )
    return out


def build_variant_table_columns(
    specs: Sequence[VariantColSpec],
) -> list[VariantTableColumn]:
    return [
        VariantTableColumn(
            label=spec.label,
            key=spec.value_key,
            fmt=spec.fmt,
            image_em_dash=spec.image_em_dash,
        )
        for spec in specs
    ]


# ---------------------------------------------------------------------------
# Derived per-variant metric helpers
# ---------------------------------------------------------------------------
# Called during report-builder variant hydration so the profile can
# reference attributes like ``cost_per_lead`` / ``cost_per_engagement``
# / ``cpc`` / ``cpm`` directly off VariantReport without scattering
# divide-by-zero logic across the codebase.


def compute_cost_per_lead(spend: Decimal | float | None, leads: int | None) -> float | None:
    if not spend or not leads or leads <= 0:
        return None
    return float(spend) / float(leads)


def compute_cost_per_engagement(
    spend: Decimal | float | None, engagements: int | None
) -> float | None:
    if not spend or not engagements or engagements <= 0:
        return None
    return float(spend) / float(engagements)


def compute_cpc(spend: Decimal | float | None, link_clicks: int | None) -> float | None:
    if not spend or not link_clicks or link_clicks <= 0:
        return None
    return float(spend) / float(link_clicks)


def compute_cpm(spend: Decimal | float | None, impressions: int | None) -> float | None:
    if not spend or not impressions or impressions <= 0:
        return None
    return (float(spend) / float(impressions)) * 1000.0


def compute_engagement_rate_pct(
    engagements: int | None, impressions: int | None
) -> float:
    if not impressions or impressions <= 0 or not engagements:
        return 0.0
    return (float(engagements) / float(impressions)) * 100.0


def compute_lpv_rate_pct(
    landing_page_views: int | None, link_clicks: int | None
) -> float:
    if not link_clicks or link_clicks <= 0 or not landing_page_views:
        return 0.0
    return (float(landing_page_views) / float(link_clicks)) * 100.0
