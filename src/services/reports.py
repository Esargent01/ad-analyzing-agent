"""Report builders — async functions that aggregate campaign data into report models.

These functions are the single source of truth for how the daily and weekly
report payloads are assembled from the database. Both the CLI commands in
``src/main.py`` and the JSON endpoints in ``src/dashboard/app.py`` call them
so that a byte-identical report shows up on every surface (email, static HTML,
and the live dashboard).

Pure read operations only. Generation (weekly variant proposals) stays in
``src/services/weekly.py`` and is invoked by the CLI before calling
``build_weekly_report``.

Pure-function helpers (``build_funnel``, ``build_diagnostics``,
``build_projection``, ``select_best_variant``) live in ``src/reports/builder.py``
and are reused here — do not duplicate them.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from uuid import UUID

from sqlalchemy import text as sa_text
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.analysis import ElementInsight, InteractionInsight
from src.models.reports import (
    DailyReport,
    FunnelStage,
    VariantReport,
    VariantSummary,
    WeeklyMetricRow,
    WeeklyReport,
)
from src.reports.builder import (
    build_diagnostics,
    build_funnel,
    build_projection,
    select_best_variant,
)
from src.services.objectives import (
    build_diagnostic_tiles,
    build_headline_metrics,
    build_summary_numbers,
    build_variant_table_columns,
    compute_cost_per_engagement,
    compute_cost_per_lead,
    compute_cpc,
    compute_cpm,
    compute_engagement_rate_pct,
    compute_lpv_rate_pct,
    profile_for,
)
from src.services.weekly import load_proposed_variants

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def build_weekly_report(
    session: AsyncSession,
    campaign_id: UUID,
    week_start: date,
    *,
    week_end: date | None = None,
    expired_count: int = 0,
    generation_paused: bool = False,
    review_url: str | None = None,
) -> WeeklyReport:
    """Assemble the ``WeeklyReport`` payload for a campaign and week.

    Args:
        session: open async DB session.
        campaign_id: campaign UUID.
        week_start: Monday of the target week.
        week_end: Sunday of the target week. Defaults to ``week_start + 6 days``.
        expired_count: number of proposals expired by the prior generation pass
            (passed through from the caller — this function does not generate).
        generation_paused: True if the prior generation pass was paused because
            the approval queue was at capacity.
        review_url: tokenized review URL to embed in the email CTA. Pass None
            when the report will be rendered for an authed dashboard.

    Returns:
        Fully populated ``WeeklyReport`` ready to hand to the email reporter,
        the static HTML renderer, or a JSON endpoint.
    """
    if week_end is None:
        week_end = week_start + timedelta(days=6)

    # KLEIBER-4: a week is "in progress" until midnight after its Sunday.
    # We compare against today's UTC date so the label flips at the same
    # boundary the cron uses to roll the week over.
    today_utc = datetime.now(UTC).date()
    is_in_progress = week_end >= today_utc

    week_start_ts = datetime(week_start.year, week_start.month, week_start.day, tzinfo=UTC)
    week_end_ts = datetime(week_end.year, week_end.month, week_end.day, tzinfo=UTC) + timedelta(
        days=1
    )

    campaign_name, objective = await _get_campaign_meta(session, campaign_id)
    profile = profile_for(objective)

    cycle_rows = await _get_cycles_in_range(session, campaign_id, week_start_ts, week_end_ts)

    totals = await _aggregate_metrics(session, campaign_id, week_start_ts, week_end_ts)

    funnel_stages = _build_funnel_stages(totals)

    all_variants = await _variant_leaderboard(session, campaign_id, week_start_ts, week_end_ts)
    best_variant = all_variants[0] if all_variants else None
    worst_variant = all_variants[-1] if len(all_variants) > 1 else None

    top_elements = await _element_rankings(session, campaign_id)
    top_interactions = await _element_interactions(session, campaign_id)

    proposed_variants = await load_proposed_variants(session, campaign_id)

    total_launched = sum(c[2] or 0 for c in cycle_rows) if cycle_rows else 0
    # variants_retired is not tracked in cycles; leave at 0 to match historical behavior.

    # Compose the weekly totals view that the objective profiles read.
    weekly_view = _weekly_totals_view(totals)

    # Build the 3-row metric grid per objective.
    metric_rows: list[WeeklyMetricRow] = [
        WeeklyMetricRow(
            title=profile.weekly_row_titles[i],
            cards=build_headline_metrics(profile.weekly_row_specs[i], weekly_view),
        )
        for i in range(3)
    ]

    # Spotlight summary + diagnostic tiles for the weekly best variant.
    best_variant_summary: list = []
    best_variant_diagnostic_tiles: list = []
    if best_variant is not None:
        best_variant_summary = build_summary_numbers(profile.summary_specs, best_variant)
        spec_set = (
            profile.image_diagnostic_specs
            if (best_variant.media_type or "").lower() == "image"
            else profile.video_diagnostic_specs
        )
        best_variant_diagnostic_tiles = build_diagnostic_tiles(spec_set, best_variant)

    variant_table_columns = build_variant_table_columns(profile.variant_col_specs)

    return WeeklyReport(
        campaign_id=campaign_id,
        campaign_name=campaign_name,
        week_start=week_start,
        week_end=week_end,
        is_in_progress=is_in_progress,
        objective=objective,
        total_spend=totals.spend,
        total_impressions=totals.impressions,
        total_clicks=totals.clicks,
        total_conversions=totals.conversions,
        avg_ctr=totals.ctr,
        avg_cpa=totals.cpa,
        total_reach=totals.reach,
        total_video_views_3s=totals.video_views_3s,
        total_video_views_15s=totals.video_views_15s,
        total_thruplays=totals.thruplays,
        total_link_clicks=totals.link_clicks,
        total_landing_page_views=totals.landing_page_views,
        total_add_to_carts=totals.add_to_carts,
        total_purchases=totals.purchases,
        total_purchase_value=totals.purchase_value,
        avg_hook_rate=totals.hook_rate,
        avg_hold_rate=totals.hold_rate,
        avg_cpm=totals.cpm,
        avg_cpc=totals.cpc if totals.cpc else Decimal("0"),
        avg_frequency=totals.frequency,
        avg_roas=totals.roas,
        avg_cost_per_purchase=totals.cost_per_purchase,
        total_leads=totals.leads,
        total_post_engagements=totals.post_engagements,
        avg_cost_per_lead=totals.cost_per_lead,
        avg_cost_per_engagement=totals.cost_per_engagement,
        lpv_rate_pct=float(totals.lpv_rate) * 100 if totals.lpv_rate else 0.0,
        funnel_stages=funnel_stages,
        best_variant=best_variant,
        worst_variant=worst_variant,
        all_variants=all_variants,
        top_elements=top_elements,
        top_interactions=top_interactions,
        cycles_run=len(cycle_rows) if cycle_rows else 0,
        variants_launched=total_launched,
        variants_retired=0,
        summary_text=f"Weekly optimization summary for {campaign_name}",
        proposed_variants=proposed_variants,
        expired_count=expired_count,
        generation_paused=generation_paused,
        review_url=review_url,
        metric_rows=metric_rows,
        best_variant_summary=best_variant_summary,
        best_variant_diagnostic_tiles=best_variant_diagnostic_tiles,
        variant_table_columns=variant_table_columns,
    )


class _WeeklyTotalsView:
    """Attribute-accessible wrapper for weekly-aggregate values that
    matches the ``value_key`` / ``prev_key`` names used in
    ``src/services/objectives.py``.

    Weekly reports don't compute week-over-week deltas (today), so
    every ``prev_*`` attribute is None — the headline-metric builder
    handles that cleanly by skipping the delta sub-line.

    The slot set intentionally mirrors :class:`_DailyTotalsView` so
    both views are interchangeable where only the shared subset is
    read.
    """

    __slots__ = (
        "total_spend",
        "total_purchases",
        "total_leads",
        "total_post_engagements",
        "total_impressions",
        "total_reach",
        "total_link_clicks",
        "total_landing_page_views",
        "avg_cost_per_purchase",
        "avg_cost_per_lead",
        "avg_cost_per_engagement",
        "avg_cpc",
        "avg_cpm",
        "avg_ctr",
        "avg_roas",
        "avg_hook_rate",
        "avg_hold_rate",
        "avg_frequency",
        "total_purchase_value",
        "lpv_rate_pct",
        "prev_spend",
        "prev_purchases",
        "prev_leads",
        "prev_post_engagements",
        "prev_link_clicks",
        "prev_impressions",
        "prev_reach",
        "prev_avg_cpa",
        "prev_avg_cpl",
        "prev_avg_cpe",
        "prev_avg_cpc",
        "prev_avg_cpm",
        "prev_avg_ctr",
        "prev_avg_roas",
    )


def _weekly_totals_view(totals: _AggregateTotals) -> _WeeklyTotalsView:
    view = _WeeklyTotalsView()
    view.total_spend = totals.spend
    view.total_purchases = totals.purchases
    view.total_leads = totals.leads
    view.total_post_engagements = totals.post_engagements
    view.total_impressions = totals.impressions
    view.total_reach = totals.reach
    view.total_link_clicks = totals.link_clicks
    view.total_landing_page_views = totals.landing_page_views
    view.avg_cost_per_purchase = (
        float(totals.cost_per_purchase) if totals.cost_per_purchase else None
    )
    view.avg_cost_per_lead = (
        float(totals.cost_per_lead) if totals.cost_per_lead else None
    )
    view.avg_cost_per_engagement = (
        float(totals.cost_per_engagement) if totals.cost_per_engagement else None
    )
    view.avg_cpc = float(totals.cpc) if totals.cpc else None
    view.avg_cpm = float(totals.cpm) if totals.cpm else 0.0
    view.avg_ctr = float(totals.ctr) * 100 if totals.ctr else 0.0
    view.avg_roas = float(totals.roas) if totals.roas else None
    view.avg_hook_rate = float(totals.hook_rate) * 100 if totals.hook_rate else 0.0
    view.avg_hold_rate = float(totals.hold_rate) * 100 if totals.hold_rate else 0.0
    view.avg_frequency = float(totals.frequency) if totals.frequency else 0.0
    view.total_purchase_value = totals.purchase_value
    view.lpv_rate_pct = float(totals.lpv_rate) * 100 if totals.lpv_rate else 0.0

    # No previous-period delta on weekly today.
    view.prev_spend = None
    view.prev_purchases = None
    view.prev_leads = None
    view.prev_post_engagements = None
    view.prev_link_clicks = None
    view.prev_impressions = None
    view.prev_reach = None
    view.prev_avg_cpa = None
    view.prev_avg_cpl = None
    view.prev_avg_cpe = None
    view.prev_avg_cpc = None
    view.prev_avg_cpm = None
    view.prev_avg_ctr = None
    view.prev_avg_roas = None
    return view


async def build_daily_report(
    session: AsyncSession,
    campaign_id: UUID,
    report_day: date,
) -> DailyReport:
    """Assemble the ``DailyReport`` payload for a campaign and single calendar day.

    Args:
        session: open async DB session.
        campaign_id: campaign UUID.
        report_day: calendar day to report on (UTC).

    Returns:
        Fully populated ``DailyReport`` including the best-variant spotlight
        (funnel, diagnostics, projection) and previous-day trend comparisons.
    """
    day_start = datetime(report_day.year, report_day.month, report_day.day, tzinfo=UTC)
    day_end = day_start + timedelta(days=1)

    campaign_name, objective = await _get_campaign_meta(session, campaign_id)
    profile = profile_for(objective)

    cycle_rows = await _get_cycles_in_range(session, campaign_id, day_start, day_end)

    totals = await _aggregate_metrics(session, campaign_id, day_start, day_end)

    all_variants = await _variant_leaderboard(session, campaign_id, day_start, day_end)

    genome_map = await _variant_genome_map(session, campaign_id)

    prev_day = report_day - timedelta(days=1)
    prev_start = datetime(prev_day.year, prev_day.month, prev_day.day, tzinfo=UTC)
    prev_end = prev_start + timedelta(days=1)
    prev_totals = await _previous_day_totals(session, campaign_id, prev_start, prev_end)

    # Convert leaderboard VariantSummary rows to the richer VariantReport shape.
    v2_variants = [_variant_summary_to_variant_report(vs, genome_map) for vs in all_variants]

    # Pick the best variant via the objective's ranker. Fall back to
    # the Sales-flavoured ``select_best_variant`` helper only if the
    # ranker returns None — this keeps the "minimum purchases" gate
    # intact for SALES campaigns.
    best_v2 = profile.best_variant_ranker(v2_variants)
    if best_v2 is None and objective in ("OUTCOME_SALES", "OUTCOME_UNKNOWN"):
        best_v2 = select_best_variant(v2_variants)

    # Compose the flat header-card + weekly-style aggregate object that
    # the objectives module reads. Attribute names must line up with
    # the ``value_key`` / ``prev_key`` strings on HeadlineSpec /
    # SummarySpec.
    totals_view = _daily_totals_view(totals, prev_totals)

    headline_metrics = build_headline_metrics(
        profile.daily_headline_specs, totals_view
    )
    best_variant_summary = (
        build_summary_numbers(profile.summary_specs, best_v2) if best_v2 else []
    )

    # Diagnostic tiles: branch on media_type, same as today but via
    # the profile's specs.
    best_variant_diagnostic_tiles: list = []
    if best_v2:
        spec_set = (
            profile.image_diagnostic_specs
            if (best_v2.media_type or "").lower() == "image"
            else profile.video_diagnostic_specs
        )
        best_variant_diagnostic_tiles = build_diagnostic_tiles(spec_set, best_v2)

    variant_table_columns = build_variant_table_columns(profile.variant_col_specs)

    return DailyReport(
        campaign_name=campaign_name,
        campaign_id=campaign_id,
        cycle_number=len(cycle_rows),
        report_date=report_day,
        day_number=1,
        objective=objective,
        total_spend=totals.spend,
        total_purchases=totals.purchases,
        avg_cost_per_purchase=(
            float(totals.cost_per_purchase) if totals.cost_per_purchase else None
        ),
        avg_roas=float(totals.roas) if totals.roas else None,
        avg_hook_rate_pct=float(totals.hook_rate) * 100 if totals.hook_rate else 0.0,
        total_leads=totals.leads,
        total_post_engagements=totals.post_engagements,
        total_impressions=totals.impressions,
        total_reach=totals.reach,
        total_link_clicks=totals.link_clicks,
        avg_cost_per_lead=float(totals.cost_per_lead) if totals.cost_per_lead else None,
        avg_cost_per_engagement=(
            float(totals.cost_per_engagement) if totals.cost_per_engagement else None
        ),
        avg_cpc=float(totals.cpc) if totals.cpc else None,
        avg_cpm=float(totals.cpm) if totals.cpm else 0.0,
        avg_ctr=float(totals.ctr) * 100 if totals.ctr else 0.0,
        prev_spend=prev_totals.spend,
        prev_purchases=prev_totals.purchases
        if prev_totals.purchases and prev_totals.purchases > 0
        else None,
        prev_avg_cpa=prev_totals.avg_cpa,
        prev_avg_roas=prev_totals.avg_roas,
        prev_leads=prev_totals.leads,
        prev_post_engagements=prev_totals.post_engagements,
        prev_link_clicks=prev_totals.link_clicks,
        prev_impressions=prev_totals.impressions,
        prev_reach=prev_totals.reach,
        prev_avg_cpl=prev_totals.avg_cpl,
        prev_avg_cpe=prev_totals.avg_cpe,
        prev_avg_cpc=prev_totals.avg_cpc,
        prev_avg_cpm=prev_totals.avg_cpm,
        prev_avg_ctr=prev_totals.avg_ctr,
        variants=sorted(
            v2_variants,
            key=lambda v: (v.cost_per_purchase is None, v.cost_per_purchase or 0),
        ),
        best_variant=best_v2,
        best_variant_funnel=build_funnel(best_v2) if best_v2 else [],
        best_variant_diagnostics=build_diagnostics(best_v2) if best_v2 else [],
        best_variant_projection=build_projection(best_v2) if best_v2 else None,
        headline_metrics=headline_metrics,
        best_variant_summary=best_variant_summary,
        best_variant_diagnostic_tiles=best_variant_diagnostic_tiles,
        variant_table_columns=variant_table_columns,
    )


class _DailyTotalsView:
    """Attribute-accessible view that maps objective-profile metric
    keys onto their values from this and yesterday's rollups.

    ``build_headline_metrics`` reads ``value_key`` / ``prev_key``
    strings off HeadlineSpec and looks them up with ``getattr`` — this
    struct is what keeps that lookup one-line and keeps the profiles
    readable (``HeadlineSpec("AVG CPA", "avg_cost_per_purchase", ...)``).
    """

    __slots__ = (
        "total_spend",
        "total_purchases",
        "total_leads",
        "total_post_engagements",
        "total_impressions",
        "total_reach",
        "total_link_clicks",
        "total_landing_page_views",
        "avg_cost_per_purchase",
        "avg_cost_per_lead",
        "avg_cost_per_engagement",
        "avg_cpc",
        "avg_cpm",
        "avg_ctr",
        "avg_roas",
        "avg_hook_rate",
        "avg_hold_rate",
        "avg_frequency",
        "total_purchase_value",
        "lpv_rate_pct",
        # Previous-day equivalents.
        "prev_spend",
        "prev_purchases",
        "prev_leads",
        "prev_post_engagements",
        "prev_link_clicks",
        "prev_impressions",
        "prev_reach",
        "prev_avg_cpa",
        "prev_avg_cpl",
        "prev_avg_cpe",
        "prev_avg_cpc",
        "prev_avg_cpm",
        "prev_avg_ctr",
        "prev_avg_roas",
    )


def _daily_totals_view(
    totals: _AggregateTotals, prev: _PreviousDayTotals
) -> _DailyTotalsView:
    view = _DailyTotalsView()
    view.total_spend = totals.spend
    view.total_purchases = totals.purchases
    view.total_leads = totals.leads
    view.total_post_engagements = totals.post_engagements
    view.total_impressions = totals.impressions
    view.total_reach = totals.reach
    view.total_link_clicks = totals.link_clicks
    view.total_landing_page_views = totals.landing_page_views
    view.avg_cost_per_purchase = (
        float(totals.cost_per_purchase) if totals.cost_per_purchase else None
    )
    view.avg_cost_per_lead = (
        float(totals.cost_per_lead) if totals.cost_per_lead else None
    )
    view.avg_cost_per_engagement = (
        float(totals.cost_per_engagement) if totals.cost_per_engagement else None
    )
    view.avg_cpc = float(totals.cpc) if totals.cpc else None
    view.avg_cpm = float(totals.cpm) if totals.cpm else 0.0
    # CTR internally is 0-1; the objective profiles expect 0-100.
    view.avg_ctr = float(totals.ctr) * 100 if totals.ctr else 0.0
    view.avg_roas = float(totals.roas) if totals.roas else None
    view.avg_hook_rate = float(totals.hook_rate) * 100 if totals.hook_rate else 0.0
    view.avg_hold_rate = float(totals.hold_rate) * 100 if totals.hold_rate else 0.0
    view.avg_frequency = float(totals.frequency) if totals.frequency else 0.0
    view.total_purchase_value = totals.purchase_value
    view.lpv_rate_pct = float(totals.lpv_rate) * 100 if totals.lpv_rate else 0.0

    view.prev_spend = prev.spend
    view.prev_purchases = prev.purchases
    view.prev_leads = prev.leads
    view.prev_post_engagements = prev.post_engagements
    view.prev_link_clicks = prev.link_clicks
    view.prev_impressions = prev.impressions
    view.prev_reach = prev.reach
    view.prev_avg_cpa = prev.avg_cpa
    view.prev_avg_cpl = prev.avg_cpl
    view.prev_avg_cpe = prev.avg_cpe
    view.prev_avg_cpc = prev.avg_cpc
    view.prev_avg_cpm = prev.avg_cpm
    view.prev_avg_ctr = prev.avg_ctr
    view.prev_avg_roas = prev.avg_roas
    return view


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


class _AggregateTotals:
    """Mutable bag of per-window aggregate totals shared between daily/weekly."""

    __slots__ = (
        "impressions",
        "clicks",
        "conversions",
        "spend",
        "reach",
        "video_views_3s",
        "video_views_15s",
        "thruplays",
        "link_clicks",
        "landing_page_views",
        "add_to_carts",
        "purchases",
        "purchase_value",
        "leads",
        "post_engagements",
        "ctr",
        "cpa",
        "cpc",
        "hook_rate",
        "hold_rate",
        "cpm",
        "frequency",
        "roas",
        "cost_per_purchase",
        "cost_per_lead",
        "cost_per_engagement",
        "lpv_rate",
    )

    def __init__(
        self,
        *,
        impressions: int,
        clicks: int,
        conversions: int,
        spend: Decimal,
        reach: int,
        video_views_3s: int,
        video_views_15s: int,
        thruplays: int,
        link_clicks: int,
        landing_page_views: int,
        add_to_carts: int,
        purchases: int,
        purchase_value: Decimal,
        leads: int = 0,
        post_engagements: int = 0,
    ) -> None:
        self.impressions = impressions
        self.clicks = clicks
        self.conversions = conversions
        self.spend = spend
        self.reach = reach
        self.video_views_3s = video_views_3s
        self.video_views_15s = video_views_15s
        self.thruplays = thruplays
        self.link_clicks = link_clicks
        self.landing_page_views = landing_page_views
        self.add_to_carts = add_to_carts
        self.purchases = purchases
        self.purchase_value = purchase_value
        self.leads = leads
        self.post_engagements = post_engagements

        self.ctr = Decimal(str(clicks / impressions)) if impressions > 0 else Decimal("0")
        self.cpa = Decimal(str(float(spend) / conversions)) if conversions > 0 else None
        self.cpc = (
            Decimal(str(float(spend) / link_clicks)) if link_clicks > 0 else None
        )
        self.hook_rate = (
            Decimal(str(video_views_3s / impressions)) if impressions > 0 else Decimal("0")
        )
        self.hold_rate = (
            Decimal(str(video_views_15s / video_views_3s)) if video_views_3s > 0 else Decimal("0")
        )
        self.cpm = (
            Decimal(str((float(spend) / impressions) * 1000)) if impressions > 0 else Decimal("0")
        )
        self.frequency = Decimal(str(impressions / reach)) if reach > 0 else Decimal("0")
        self.roas = (
            Decimal(str(float(purchase_value) / float(spend)))
            if float(spend) > 0 and float(purchase_value) > 0
            else None
        )
        self.cost_per_purchase = Decimal(str(float(spend) / purchases)) if purchases > 0 else None
        self.cost_per_lead = (
            Decimal(str(float(spend) / leads)) if leads > 0 else None
        )
        self.cost_per_engagement = (
            Decimal(str(float(spend) / post_engagements))
            if post_engagements > 0
            else None
        )
        self.lpv_rate = (
            Decimal(str(landing_page_views / link_clicks)) if link_clicks > 0 else Decimal("0")
        )


class _PreviousDayTotals:
    """Trimmed view of the previous day's rollup for trend comparisons."""

    __slots__ = (
        "spend",
        "purchases",
        "avg_cpa",
        "avg_roas",
        "leads",
        "post_engagements",
        "link_clicks",
        "impressions",
        "reach",
        "avg_cpl",
        "avg_cpe",
        "avg_cpc",
        "avg_cpm",
        "avg_ctr",
    )

    def __init__(
        self,
        *,
        spend: Decimal | None,
        purchases: int | None,
        avg_cpa: float | None,
        avg_roas: float | None,
        leads: int | None = None,
        post_engagements: int | None = None,
        link_clicks: int | None = None,
        impressions: int | None = None,
        reach: int | None = None,
        avg_cpl: float | None = None,
        avg_cpe: float | None = None,
        avg_cpc: float | None = None,
        avg_cpm: float | None = None,
        avg_ctr: float | None = None,
    ) -> None:
        self.spend = spend
        self.purchases = purchases
        self.avg_cpa = avg_cpa
        self.avg_roas = avg_roas
        self.leads = leads
        self.post_engagements = post_engagements
        self.link_clicks = link_clicks
        self.impressions = impressions
        self.reach = reach
        self.avg_cpl = avg_cpl
        self.avg_cpe = avg_cpe
        self.avg_cpc = avg_cpc
        self.avg_cpm = avg_cpm
        self.avg_ctr = avg_ctr


async def _get_campaign_name(session: AsyncSession, campaign_id: UUID) -> str:
    """Fetch the campaign name; raises ``LookupError`` if the id is unknown."""
    row = await session.execute(
        sa_text("SELECT name FROM campaigns WHERE id = :id"),
        {"id": str(campaign_id)},
    )
    result = row.fetchone()
    if not result:
        raise LookupError(f"Campaign {campaign_id} not found")
    return str(result[0])


async def _get_campaign_meta(
    session: AsyncSession, campaign_id: UUID
) -> tuple[str, str]:
    """Fetch ``(name, objective)`` for a campaign.

    Used by the report builders so both fields come through a single
    query. Raises ``LookupError`` if the campaign row doesn't exist.
    """
    row = await session.execute(
        sa_text("SELECT name, objective FROM campaigns WHERE id = :id"),
        {"id": str(campaign_id)},
    )
    result = row.fetchone()
    if not result:
        raise LookupError(f"Campaign {campaign_id} not found")
    return str(result[0]), str(result[1]) if result[1] else "OUTCOME_SALES"


async def _get_cycles_in_range(
    session: AsyncSession,
    campaign_id: UUID,
    start: datetime,
    end: datetime,
) -> list:
    """Return ``test_cycles`` rows within ``[start, end)``."""
    row = await session.execute(
        sa_text(
            """
            SELECT cycle_number, phase, variants_launched, variants_paused,
                   variants_promoted, summary_text, started_at
            FROM test_cycles
            WHERE campaign_id = :id
              AND started_at >= :ws AND started_at < :we
            ORDER BY cycle_number DESC
            """
        ),
        {"id": str(campaign_id), "ws": start, "we": end},
    )
    return row.fetchall()


async def _aggregate_metrics(
    session: AsyncSession,
    campaign_id: UUID,
    start: datetime,
    end: datetime,
) -> _AggregateTotals:
    """Aggregate full-funnel metrics for a campaign over a time window."""
    row = await session.execute(
        sa_text(
            """
            SELECT COALESCE(SUM(m.impressions), 0),
                   COALESCE(SUM(m.clicks), 0),
                   COALESCE(SUM(m.conversions), 0),
                   COALESCE(SUM(m.spend), 0),
                   COALESCE(SUM(m.reach), 0),
                   COALESCE(SUM(m.video_views_3s), 0),
                   COALESCE(SUM(m.video_views_15s), 0),
                   COALESCE(SUM(m.thruplays), 0),
                   COALESCE(SUM(m.link_clicks), 0),
                   COALESCE(SUM(m.landing_page_views), 0),
                   COALESCE(SUM(m.add_to_carts), 0),
                   COALESCE(SUM(m.purchases), 0),
                   COALESCE(SUM(m.purchase_value), 0),
                   COALESCE(SUM(m.leads), 0),
                   COALESCE(SUM(m.post_engagements), 0)
            FROM metrics m
            JOIN variants v ON v.id = m.variant_id
            WHERE v.campaign_id = :id
              AND m.recorded_at >= :ws AND m.recorded_at < :we
            """
        ),
        {"id": str(campaign_id), "ws": start, "we": end},
    )
    m = row.fetchone()
    return _AggregateTotals(
        impressions=int(m[0]),
        clicks=int(m[1]),
        conversions=int(m[2]),
        spend=Decimal(str(m[3])),
        reach=int(m[4]),
        video_views_3s=int(m[5]),
        video_views_15s=int(m[6]),
        thruplays=int(m[7]),
        link_clicks=int(m[8]),
        landing_page_views=int(m[9]),
        add_to_carts=int(m[10]),
        purchases=int(m[11]),
        purchase_value=Decimal(str(m[12])),
        leads=int(m[13]),
        post_engagements=int(m[14]),
    )


def _build_funnel_stages(t: _AggregateTotals) -> list[FunnelStage]:
    """Build the list of ``FunnelStage`` entries for the weekly report card.

    Mirrors the historical main.py logic exactly so the rendered HTML stays
    byte-identical through the refactor.
    """
    spend_f = float(t.spend)
    stages: list[FunnelStage] = [
        FunnelStage(
            stage_name="Impressions",
            value=t.impressions,
            rate=None,
            cost_per=(
                Decimal(str(round(spend_f / t.impressions * 1000, 2)))
                if t.impressions > 0
                else None
            ),
        ),
        FunnelStage(
            stage_name="Reach",
            value=t.reach,
            rate=None,
            cost_per=(Decimal(str(round(spend_f / t.reach * 1000, 2))) if t.reach > 0 else None),
        ),
    ]
    if t.video_views_3s > 0:
        stages.append(
            FunnelStage(
                stage_name="Video Views (3s)",
                value=t.video_views_3s,
                rate=(
                    Decimal(str(round(t.video_views_3s / t.impressions, 4)))
                    if t.impressions > 0
                    else None
                ),
                cost_per=(
                    Decimal(str(round(spend_f / t.video_views_3s, 2)))
                    if t.video_views_3s > 0
                    else None
                ),
            )
        )
    if t.video_views_15s > 0:
        stages.append(
            FunnelStage(
                stage_name="Video Views (15s)",
                value=t.video_views_15s,
                rate=(
                    Decimal(str(round(t.video_views_15s / t.video_views_3s, 4)))
                    if t.video_views_3s > 0
                    else None
                ),
                cost_per=(
                    Decimal(str(round(spend_f / t.video_views_15s, 2)))
                    if t.video_views_15s > 0
                    else None
                ),
            )
        )
    if t.link_clicks > 0:
        stages.append(
            FunnelStage(
                stage_name="Link Clicks",
                value=t.link_clicks,
                rate=(
                    Decimal(str(round(t.link_clicks / t.impressions, 4)))
                    if t.impressions > 0
                    else None
                ),
                cost_per=Decimal(str(round(spend_f / t.link_clicks, 2))),
            )
        )
    if t.landing_page_views > 0:
        stages.append(
            FunnelStage(
                stage_name="Landing Page Views",
                value=t.landing_page_views,
                rate=(
                    Decimal(str(round(t.landing_page_views / t.link_clicks, 4)))
                    if t.link_clicks > 0
                    else None
                ),
                cost_per=Decimal(str(round(spend_f / t.landing_page_views, 2))),
            )
        )
    if t.add_to_carts > 0:
        stages.append(
            FunnelStage(
                stage_name="Add to Carts",
                value=t.add_to_carts,
                rate=(
                    Decimal(str(round(t.add_to_carts / t.landing_page_views, 4)))
                    if t.landing_page_views > 0
                    else None
                ),
                cost_per=Decimal(str(round(spend_f / t.add_to_carts, 2))),
            )
        )
    if t.purchases > 0:
        stages.append(
            FunnelStage(
                stage_name="Purchases",
                value=t.purchases,
                rate=(
                    Decimal(str(round(t.purchases / t.add_to_carts, 4)))
                    if t.add_to_carts > 0
                    else None
                ),
                cost_per=Decimal(str(round(spend_f / t.purchases, 2))),
            )
        )
    return stages


async def _variant_leaderboard(
    session: AsyncSession,
    campaign_id: UUID,
    start: datetime,
    end: datetime,
) -> list[VariantSummary]:
    """Per-variant aggregates for active/winner/paused variants in the window."""
    row = await session.execute(
        sa_text(
            """
            SELECT v.id, v.variant_code, v.status,
                   COALESCE(m.impressions, 0), COALESCE(m.clicks, 0),
                   COALESCE(m.conversions, 0), COALESCE(m.spend, 0),
                   COALESCE(m.reach, 0), COALESCE(m.video_views_3s, 0),
                   COALESCE(m.video_views_15s, 0), COALESCE(m.thruplays, 0),
                   COALESCE(m.link_clicks, 0), COALESCE(m.landing_page_views, 0),
                   COALESCE(m.add_to_carts, 0), COALESCE(m.purchases, 0),
                   COALESCE(m.purchase_value, 0),
                   v.media_type,
                   COALESCE(m.leads, 0), COALESCE(m.post_engagements, 0)
            FROM variants v
            LEFT JOIN LATERAL (
                SELECT SUM(impressions) AS impressions, SUM(clicks) AS clicks,
                       SUM(conversions) AS conversions, SUM(spend) AS spend,
                       SUM(reach) AS reach, SUM(video_views_3s) AS video_views_3s,
                       SUM(video_views_15s) AS video_views_15s, SUM(thruplays) AS thruplays,
                       SUM(link_clicks) AS link_clicks, SUM(landing_page_views) AS landing_page_views,
                       SUM(add_to_carts) AS add_to_carts, SUM(purchases) AS purchases,
                       SUM(purchase_value) AS purchase_value,
                       SUM(leads) AS leads, SUM(post_engagements) AS post_engagements
                FROM metrics WHERE variant_id = v.id
                  AND recorded_at >= :ws AND recorded_at < :we
            ) m ON TRUE
            WHERE v.campaign_id = :id AND v.status IN ('active', 'winner', 'paused')
            ORDER BY CASE WHEN COALESCE(m.purchases, 0) > 0 AND COALESCE(m.spend, 0) > 0
                          THEN COALESCE(m.purchase_value, 0)::NUMERIC / m.spend
                          WHEN COALESCE(m.impressions, 0) > 0
                          THEN COALESCE(m.clicks, 0)::NUMERIC / m.impressions
                          ELSE 0 END DESC
            """
        ),
        {"id": str(campaign_id), "ws": start, "we": end},
    )
    return [_row_to_variant_summary(r) for r in row.fetchall()]


def _row_to_variant_summary(row) -> VariantSummary:
    """Translate a leaderboard row tuple into a ``VariantSummary``."""
    imps = int(row[3])
    clicks = int(row[4])
    convs = int(row[5])
    spend = Decimal(str(row[6]))
    reach = int(row[7])
    vv3s = int(row[8])
    vv15s = int(row[9])
    thruplays = int(row[10])
    lc = int(row[11])
    lpv = int(row[12])
    atc = int(row[13])
    purch = int(row[14])
    pv = Decimal(str(row[15]))
    media_type = str(row[16]) if len(row) > 16 and row[16] else "unknown"
    leads = int(row[17]) if len(row) > 17 and row[17] is not None else 0
    post_engagements = int(row[18]) if len(row) > 18 and row[18] is not None else 0

    ctr = Decimal(str(clicks / imps)) if imps > 0 else Decimal("0")
    cpa = Decimal(str(float(spend) / convs)) if convs > 0 else None
    hr = Decimal(str(vv3s / imps)) if imps > 0 else Decimal("0")
    hold = Decimal(str(vv15s / vv3s)) if vv3s > 0 else Decimal("0")
    cpp = Decimal(str(float(spend) / purch)) if purch > 0 else None
    roas = Decimal(str(float(pv) / float(spend))) if float(spend) > 0 and float(pv) > 0 else None

    # Objective-aware derived fields. ``None`` for cost metrics when
    # the denominator is zero keeps downstream em-dash rendering
    # consistent with the sales-only behaviour (CPA/ROAS em-dash when
    # purchases == 0).
    cpc = Decimal(str(float(spend) / lc)) if lc > 0 else None
    cpl = Decimal(str(float(spend) / leads)) if leads > 0 else None
    cpe = (
        Decimal(str(float(spend) / post_engagements))
        if post_engagements > 0
        else None
    )
    cpm = (
        Decimal(str((float(spend) / imps) * 1000)) if imps > 0 else Decimal("0")
    )
    frequency = Decimal(str(imps / reach)) if reach > 0 else Decimal("0")

    # Rates in 0-100 pct (convenience for the variant table).
    hook_rate_pct = (vv3s / imps * 100) if imps > 0 else 0.0
    hold_rate_pct = (vv15s / vv3s * 100) if vv3s > 0 else 0.0
    ctr_pct = (lc / imps * 100) if imps > 0 else 0.0

    return VariantSummary(
        variant_id=row[0],
        variant_code=str(row[1]),
        status=str(row[2]),
        impressions=imps,
        clicks=clicks,
        conversions=convs,
        spend=spend,
        ctr=ctr,
        cpa=cpa,
        reach=reach,
        video_views_3s=vv3s,
        video_views_15s=vv15s,
        thruplays=thruplays,
        link_clicks=lc,
        landing_page_views=lpv,
        add_to_carts=atc,
        purchases=purch,
        purchase_value=pv,
        hook_rate=hr,
        hold_rate=hold,
        cost_per_purchase=cpp,
        roas=roas,
        media_type=media_type,
        leads=leads,
        post_engagements=post_engagements,
        cost_per_lead=cpl,
        cost_per_engagement=cpe,
        cpc=cpc,
        cpm=cpm,
        frequency=frequency,
        hook_rate_pct=hook_rate_pct,
        hold_rate_pct=hold_rate_pct,
        ctr_pct=ctr_pct,
    )


async def _element_rankings(session: AsyncSession, campaign_id: UUID) -> list[ElementInsight]:
    """Top 20 element performance rows, ordered by average CTR."""
    row = await session.execute(
        sa_text(
            """
            SELECT slot_name, slot_value, avg_ctr, avg_cpa, variants_tested,
                   best_ctr, worst_ctr, total_impressions, total_conversions, confidence,
                   avg_hook_rate, avg_roas, best_hook_rate, best_cpa, total_purchases
            FROM element_performance
            WHERE campaign_id = :id AND variants_tested >= 1
            ORDER BY avg_ctr DESC NULLS LAST
            LIMIT 20
            """
        ),
        {"id": str(campaign_id)},
    )
    return [
        ElementInsight(
            slot_name=str(r[0]),
            slot_value=str(r[1]),
            avg_ctr=Decimal(str(r[2] or 0)),
            avg_cpa=Decimal(str(r[3])) if r[3] else None,
            variants_tested=int(r[4]),
            best_ctr=Decimal(str(r[5])) if r[5] else None,
            worst_ctr=Decimal(str(r[6])) if r[6] else None,
            total_impressions=int(r[7]),
            total_conversions=int(r[8]),
            confidence=Decimal(str(r[9])) if r[9] else None,
            avg_hook_rate=Decimal(str(r[10])) if r[10] else None,
            avg_roas=Decimal(str(r[11])) if r[11] else None,
            best_hook_rate=Decimal(str(r[12])) if r[12] else None,
            best_cpa=Decimal(str(r[13])) if r[13] else None,
            total_purchases=int(r[14]) if r[14] else 0,
        )
        for r in row.fetchall()
    ]


async def _element_interactions(
    session: AsyncSession, campaign_id: UUID
) -> list[InteractionInsight]:
    """Top 10 element-pair interactions, ranked by absolute interaction lift."""
    row = await session.execute(
        sa_text(
            """
            SELECT slot_a_name, slot_a_value, slot_b_name, slot_b_value,
                   variants_tested, combined_avg_ctr, solo_a_avg_ctr,
                   solo_b_avg_ctr, interaction_lift, confidence
            FROM element_interactions
            WHERE campaign_id = :id
            ORDER BY ABS(interaction_lift) DESC NULLS LAST
            LIMIT 10
            """
        ),
        {"id": str(campaign_id)},
    )
    return [
        InteractionInsight(
            slot_a_name=str(r[0]),
            slot_a_value=str(r[1]),
            slot_b_name=str(r[2]),
            slot_b_value=str(r[3]),
            variants_tested=int(r[4]),
            combined_avg_ctr=Decimal(str(r[5] or 0)),
            solo_a_avg_ctr=Decimal(str(r[6])) if r[6] else None,
            solo_b_avg_ctr=Decimal(str(r[7])) if r[7] else None,
            interaction_lift=Decimal(str(r[8])) if r[8] else None,
            confidence=Decimal(str(r[9])) if r[9] else None,
        )
        for r in row.fetchall()
    ]


async def _variant_genome_map(session: AsyncSession, campaign_id: UUID) -> dict[str, dict]:
    """Look up ``{variant_id: {genome, hypothesis, days_active, media_type}}`` for enrichment."""
    row = await session.execute(
        sa_text(
            """
            SELECT v.id, v.genome, v.hypothesis,
                   EXTRACT(DAY FROM NOW() - v.created_at)::INT AS days_active,
                   v.media_type
            FROM variants v
            WHERE v.campaign_id = :id AND v.status IN ('active', 'winner', 'paused')
            """
        ),
        {"id": str(campaign_id)},
    )
    return {
        str(r[0]): {
            "genome": r[1] or {},
            "hypothesis": r[2],
            "days_active": int(r[3] or 1),
            "media_type": r[4] or "unknown",
        }
        for r in row.fetchall()
    }


async def _previous_day_totals(
    session: AsyncSession,
    campaign_id: UUID,
    start: datetime,
    end: datetime,
) -> _PreviousDayTotals:
    """Minimal roll-up for the previous day — all objective-aware
    trend fields. Cheap because it's one SUM query."""
    row = await session.execute(
        sa_text(
            """
            SELECT COALESCE(SUM(m.spend), 0),
                   COALESCE(SUM(m.purchases), 0),
                   COALESCE(SUM(m.purchase_value), 0),
                   COALESCE(SUM(m.leads), 0),
                   COALESCE(SUM(m.post_engagements), 0),
                   COALESCE(SUM(m.link_clicks), 0),
                   COALESCE(SUM(m.impressions), 0),
                   COALESCE(SUM(m.reach), 0),
                   COALESCE(SUM(m.clicks), 0)
            FROM metrics m
            JOIN variants v ON v.id = m.variant_id
            WHERE v.campaign_id = :id
              AND m.recorded_at >= :ps AND m.recorded_at < :pe
            """
        ),
        {"id": str(campaign_id), "ps": start, "pe": end},
    )
    prev = row.fetchone()
    prev_spend = Decimal(str(prev[0])) if prev and float(prev[0]) > 0 else None
    prev_purchases = int(prev[1]) if prev else None
    prev_pv = Decimal(str(prev[2])) if prev else Decimal("0")
    prev_leads_n = int(prev[3]) if prev and prev[3] is not None else 0
    prev_engagements_n = int(prev[4]) if prev and prev[4] is not None else 0
    prev_link_clicks_n = int(prev[5]) if prev and prev[5] is not None else 0
    prev_impressions_n = int(prev[6]) if prev and prev[6] is not None else 0
    prev_reach_n = int(prev[7]) if prev and prev[7] is not None else 0
    prev_clicks_n = int(prev[8]) if prev and prev[8] is not None else 0

    spend_f = float(prev_spend) if prev_spend else 0.0
    prev_avg_cpa = spend_f / int(prev[1]) if prev_spend and int(prev[1]) > 0 else None
    prev_avg_roas = (
        float(prev_pv) / spend_f
        if prev_spend and spend_f > 0 and float(prev_pv) > 0
        else None
    )
    prev_avg_cpl = spend_f / prev_leads_n if prev_spend and prev_leads_n > 0 else None
    prev_avg_cpe = (
        spend_f / prev_engagements_n if prev_spend and prev_engagements_n > 0 else None
    )
    prev_avg_cpc = (
        spend_f / prev_link_clicks_n if prev_spend and prev_link_clicks_n > 0 else None
    )
    prev_avg_cpm = (
        (spend_f / prev_impressions_n) * 1000 if prev_impressions_n > 0 else None
    )
    prev_avg_ctr = (
        (prev_clicks_n / prev_impressions_n) * 100 if prev_impressions_n > 0 else None
    )

    return _PreviousDayTotals(
        spend=prev_spend,
        purchases=prev_purchases,
        avg_cpa=prev_avg_cpa,
        avg_roas=prev_avg_roas,
        leads=prev_leads_n if prev_leads_n else None,
        post_engagements=prev_engagements_n if prev_engagements_n else None,
        link_clicks=prev_link_clicks_n if prev_link_clicks_n else None,
        impressions=prev_impressions_n if prev_impressions_n else None,
        reach=prev_reach_n if prev_reach_n else None,
        avg_cpl=prev_avg_cpl,
        avg_cpe=prev_avg_cpe,
        avg_cpc=prev_avg_cpc,
        avg_cpm=prev_avg_cpm,
        avg_ctr=prev_avg_ctr,
    )


def _variant_summary_to_variant_report(
    vs: VariantSummary, genome_map: dict[str, dict]
) -> VariantReport:
    """Convert a legacy ``VariantSummary`` into the richer ``VariantReport`` shape.

    Enriches with genome + hypothesis + days_active via ``genome_map`` (keyed by
    stringified variant id). Produces the same fields the old inline
    ``_to_variant_report`` helper in ``src/main.py`` did so the rendered HTML
    stays byte-identical.
    """
    imps = vs.impressions
    vv3s = vs.video_views_3s
    vv15s = vs.video_views_15s
    lc = vs.link_clicks
    atc = vs.add_to_carts
    purch = vs.purchases

    hr_pct = (vv3s / imps * 100) if imps > 0 else 0.0
    hold_pct = (vv15s / vv3s * 100) if vv3s > 0 else 0.0
    ctr_pct = (lc / imps * 100) if imps > 0 else 0.0
    atc_pct = (atc / lc * 100) if lc > 0 else 0.0
    checkout_pct = (purch / atc * 100) if atc > 0 else 0.0
    freq = (imps / vs.reach) if vs.reach > 0 else 0.0
    cpp = float(vs.cost_per_purchase) if vs.cost_per_purchase else None
    roas_v = float(vs.roas) if vs.roas else None

    gdata = genome_map.get(str(vs.variant_id), {})
    genome = gdata.get("genome", {}) if gdata else {}
    hypothesis = gdata.get("hypothesis") if gdata else None
    days_active = gdata.get("days_active", 1) if gdata else 1
    media_type = gdata.get("media_type", "unknown") if gdata else "unknown"

    summary_parts = []
    if genome.get("headline"):
        summary_parts.append(genome["headline"][:30])
    if genome.get("cta_text"):
        summary_parts.append(genome["cta_text"])
    genome_summary = " + ".join(summary_parts) if summary_parts else vs.variant_code

    # Objective-aware derived metrics. Read straight off the
    # VariantSummary (which the leaderboard query already populates)
    # so we don't re-derive the same Decimals here.
    leads = vs.leads
    post_engagements = vs.post_engagements
    cpl_v = float(vs.cost_per_lead) if vs.cost_per_lead else None
    cpe_v = float(vs.cost_per_engagement) if vs.cost_per_engagement else None
    cpc_v = float(vs.cpc) if vs.cpc else None
    cpm_v = float(vs.cpm) if vs.cpm else 0.0
    engagement_rate = compute_engagement_rate_pct(post_engagements, imps)

    return VariantReport(
        variant_id=vs.variant_id,
        variant_code=vs.variant_code,
        genome=genome,
        genome_summary=genome_summary,
        hypothesis=hypothesis,
        status=vs.status,
        days_active=days_active,
        media_type=media_type,
        spend=vs.spend,
        purchases=purch,
        purchase_value=vs.purchase_value,
        cost_per_purchase=cpp,
        roas=roas_v,
        impressions=imps,
        reach=vs.reach,
        video_views_3s=vv3s,
        video_views_15s=vv15s,
        link_clicks=lc,
        landing_page_views=vs.landing_page_views,
        add_to_carts=atc,
        hook_rate_pct=hr_pct,
        hold_rate_pct=hold_pct,
        ctr_pct=ctr_pct,
        atc_rate_pct=atc_pct,
        checkout_rate_pct=checkout_pct,
        frequency=freq,
        leads=leads,
        post_engagements=post_engagements,
        cost_per_lead=cpl_v,
        cost_per_engagement=cpe_v,
        engagement_rate_pct=engagement_rate,
        cpc=cpc_v,
        cpm=cpm_v,
    )


# Helper constant kept for convenience — computes the default "last full week".
def default_last_full_week(today: date | None = None) -> tuple[date, date]:
    """Return (Monday, Sunday) of the most recent completed week.

    Mirrors the behavior of the old ``weekly_report`` CLI: "previous full week,
    Monday through Sunday". Split out so the CLI and API can share it.
    """
    ref = today or date.today()
    week_end = ref - timedelta(days=ref.weekday() + 1)  # last Sunday
    week_start = week_end - timedelta(days=6)  # Monday before
    return week_start, week_end
