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
    WeeklyReport,
)
from src.reports.builder import (
    build_diagnostics,
    build_funnel,
    build_projection,
    select_best_variant,
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

    week_start_ts = datetime(week_start.year, week_start.month, week_start.day, tzinfo=UTC)
    week_end_ts = datetime(week_end.year, week_end.month, week_end.day, tzinfo=UTC) + timedelta(
        days=1
    )

    campaign_name = await _get_campaign_name(session, campaign_id)

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

    return WeeklyReport(
        campaign_id=campaign_id,
        campaign_name=campaign_name,
        week_start=week_start,
        week_end=week_end,
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
        avg_frequency=totals.frequency,
        avg_roas=totals.roas,
        avg_cost_per_purchase=totals.cost_per_purchase,
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
    )


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

    campaign_name = await _get_campaign_name(session, campaign_id)

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
    best_v2 = select_best_variant(v2_variants)

    return DailyReport(
        campaign_name=campaign_name,
        campaign_id=campaign_id,
        cycle_number=len(cycle_rows),
        report_date=report_day,
        day_number=1,
        total_spend=totals.spend,
        total_purchases=totals.purchases,
        avg_cost_per_purchase=(
            float(totals.cost_per_purchase) if totals.cost_per_purchase else None
        ),
        avg_roas=float(totals.roas) if totals.roas else None,
        avg_hook_rate_pct=float(totals.hook_rate) * 100 if totals.hook_rate else 0.0,
        prev_spend=prev_totals.spend,
        prev_purchases=prev_totals.purchases
        if prev_totals.purchases and prev_totals.purchases > 0
        else None,
        prev_avg_cpa=prev_totals.avg_cpa,
        prev_avg_roas=prev_totals.avg_roas,
        variants=sorted(
            v2_variants,
            key=lambda v: (v.cost_per_purchase is None, v.cost_per_purchase or 0),
        ),
        best_variant=best_v2,
        best_variant_funnel=build_funnel(best_v2) if best_v2 else [],
        best_variant_diagnostics=build_diagnostics(best_v2) if best_v2 else [],
        best_variant_projection=build_projection(best_v2) if best_v2 else None,
    )


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
        "ctr",
        "cpa",
        "hook_rate",
        "hold_rate",
        "cpm",
        "frequency",
        "roas",
        "cost_per_purchase",
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

        self.ctr = Decimal(str(clicks / impressions)) if impressions > 0 else Decimal("0")
        self.cpa = Decimal(str(float(spend) / conversions)) if conversions > 0 else None
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


class _PreviousDayTotals:
    """Trimmed view of the previous day's rollup for trend comparisons."""

    __slots__ = ("spend", "purchases", "avg_cpa", "avg_roas")

    def __init__(
        self,
        *,
        spend: Decimal | None,
        purchases: int | None,
        avg_cpa: float | None,
        avg_roas: float | None,
    ) -> None:
        self.spend = spend
        self.purchases = purchases
        self.avg_cpa = avg_cpa
        self.avg_roas = avg_roas


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
                   COALESCE(SUM(m.purchase_value), 0)
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
                   COALESCE(m.purchase_value, 0)
            FROM variants v
            LEFT JOIN LATERAL (
                SELECT SUM(impressions) AS impressions, SUM(clicks) AS clicks,
                       SUM(conversions) AS conversions, SUM(spend) AS spend,
                       SUM(reach) AS reach, SUM(video_views_3s) AS video_views_3s,
                       SUM(video_views_15s) AS video_views_15s, SUM(thruplays) AS thruplays,
                       SUM(link_clicks) AS link_clicks, SUM(landing_page_views) AS landing_page_views,
                       SUM(add_to_carts) AS add_to_carts, SUM(purchases) AS purchases,
                       SUM(purchase_value) AS purchase_value
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

    ctr = Decimal(str(clicks / imps)) if imps > 0 else Decimal("0")
    cpa = Decimal(str(float(spend) / convs)) if convs > 0 else None
    hr = Decimal(str(vv3s / imps)) if imps > 0 else Decimal("0")
    hold = Decimal(str(vv15s / vv3s)) if vv3s > 0 else Decimal("0")
    cpp = Decimal(str(float(spend) / purch)) if purch > 0 else None
    roas = Decimal(str(float(pv) / float(spend))) if float(spend) > 0 and float(pv) > 0 else None

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
    """Look up ``{variant_id: {genome, hypothesis, days_active}}`` for enrichment."""
    row = await session.execute(
        sa_text(
            """
            SELECT v.id, v.genome, v.hypothesis,
                   EXTRACT(DAY FROM NOW() - v.created_at)::INT AS days_active
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
        }
        for r in row.fetchall()
    }


async def _previous_day_totals(
    session: AsyncSession,
    campaign_id: UUID,
    start: datetime,
    end: datetime,
) -> _PreviousDayTotals:
    """Minimal roll-up for the previous day — only the fields the trend card needs."""
    row = await session.execute(
        sa_text(
            """
            SELECT COALESCE(SUM(m.spend), 0),
                   COALESCE(SUM(m.purchases), 0),
                   COALESCE(SUM(m.purchase_value), 0)
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
    prev_avg_cpa = float(prev_spend) / int(prev[1]) if prev_spend and int(prev[1]) > 0 else None
    prev_avg_roas = (
        float(prev_pv) / float(prev_spend)
        if prev_spend and float(prev_spend) > 0 and float(prev_pv) > 0
        else None
    )
    return _PreviousDayTotals(
        spend=prev_spend,
        purchases=prev_purchases,
        avg_cpa=prev_avg_cpa,
        avg_roas=prev_avg_roas,
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

    summary_parts = []
    if genome.get("headline"):
        summary_parts.append(genome["headline"][:30])
    if genome.get("cta_text"):
        summary_parts.append(genome["cta_text"])
    genome_summary = " + ".join(summary_parts) if summary_parts else vs.variant_code

    return VariantReport(
        variant_id=vs.variant_id,
        variant_code=vs.variant_code,
        genome=genome,
        genome_summary=genome_summary,
        hypothesis=hypothesis,
        status=vs.status,
        days_active=days_active,
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
