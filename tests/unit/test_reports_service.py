"""Unit tests for ``src.services.reports``.

The service has two layers:
- Pure helpers (``_build_funnel_stages``, ``_row_to_variant_summary``,
  ``_variant_summary_to_variant_report``, ``default_last_full_week``) that can
  be exercised directly with fabricated inputs.
- Async public functions (``build_weekly_report``, ``build_daily_report``) that
  orchestrate DB reads. Those are covered with a fake AsyncSession that returns
  canned result rows — no real Postgres needed.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest

from src.models.reports import FunnelStage, VariantSummary
from src.services.reports import (
    _AggregateTotals,
    _build_funnel_stages,
    _row_to_variant_summary,
    _variant_summary_to_variant_report,
    build_daily_report,
    build_weekly_report,
    default_last_full_week,
)


# ---------------------------------------------------------------------------
# default_last_full_week
# ---------------------------------------------------------------------------


class TestDefaultLastFullWeek:
    def test_tuesday_reference_returns_prior_monday_sunday(self):
        # 2026-04-07 is a Tuesday → last full week is 2026-03-30 (Mon) to 2026-04-05 (Sun)
        start, end = default_last_full_week(date(2026, 4, 7))
        assert start == date(2026, 3, 30)
        assert end == date(2026, 4, 5)
        assert start.weekday() == 0  # Monday
        assert end.weekday() == 6  # Sunday

    def test_monday_reference_returns_prior_mon_sun(self):
        # Monday 2026-04-06 → prior week is 2026-03-30 to 2026-04-05
        start, end = default_last_full_week(date(2026, 4, 6))
        assert start == date(2026, 3, 30)
        assert end == date(2026, 4, 5)

    def test_sunday_reference_returns_prior_mon_sun(self):
        # Sunday 2026-04-05 → last full week was the Monday–Sunday ending Saturday
        start, end = default_last_full_week(date(2026, 4, 5))
        assert start == date(2026, 3, 23)
        assert end == date(2026, 3, 29)

    def test_week_is_exactly_seven_days(self):
        start, end = default_last_full_week(date(2026, 4, 7))
        delta = (end - start).days
        assert delta == 6  # Mon to Sun inclusive is 6 day increments


# ---------------------------------------------------------------------------
# _build_funnel_stages
# ---------------------------------------------------------------------------


def _make_totals(**overrides) -> _AggregateTotals:
    defaults = dict(
        impressions=10000,
        clicks=200,
        conversions=10,
        spend=Decimal("100.00"),
        reach=8000,
        video_views_3s=3500,
        video_views_15s=1200,
        thruplays=800,
        link_clicks=200,
        landing_page_views=180,
        add_to_carts=40,
        purchases=10,
        purchase_value=Decimal("500.00"),
    )
    defaults.update(overrides)
    return _AggregateTotals(**defaults)


class TestBuildFunnelStages:
    def test_always_includes_impressions_and_reach(self):
        stages = _build_funnel_stages(_make_totals())
        names = [s.stage_name for s in stages]
        assert names[0] == "Impressions"
        assert names[1] == "Reach"

    def test_skips_zero_stages(self):
        totals = _make_totals(
            video_views_3s=0,
            video_views_15s=0,
            link_clicks=0,
            landing_page_views=0,
            add_to_carts=0,
            purchases=0,
        )
        stages = _build_funnel_stages(totals)
        assert [s.stage_name for s in stages] == ["Impressions", "Reach"]

    def test_full_funnel_all_stages_present(self):
        stages = _build_funnel_stages(_make_totals())
        assert len(stages) == 8
        assert [s.stage_name for s in stages] == [
            "Impressions",
            "Reach",
            "Video Views (3s)",
            "Video Views (15s)",
            "Link Clicks",
            "Landing Page Views",
            "Add to Carts",
            "Purchases",
        ]

    def test_purchase_cost_per(self):
        # 10 purchases on $100 spend → $10 per purchase
        stages = _build_funnel_stages(_make_totals())
        purchases = next(s for s in stages if s.stage_name == "Purchases")
        assert purchases.cost_per == Decimal("10.0")

    def test_returns_funnel_stage_models(self):
        stages = _build_funnel_stages(_make_totals())
        for s in stages:
            assert isinstance(s, FunnelStage)

    def test_zero_impressions_returns_none_cost_per(self):
        totals = _make_totals(impressions=0, reach=0)
        stages = _build_funnel_stages(totals)
        assert stages[0].cost_per is None
        assert stages[1].cost_per is None


# ---------------------------------------------------------------------------
# _row_to_variant_summary
# ---------------------------------------------------------------------------


class TestRowToVariantSummary:
    def test_translates_row_into_variant_summary(self):
        variant_id = uuid4()
        row = (
            variant_id,
            "V1",
            "active",
            10000,  # impressions
            500,  # clicks
            50,  # conversions
            Decimal("200.00"),  # spend
            8000,  # reach
            3500,  # vv3s
            1200,  # vv15s
            800,  # thruplays
            500,  # link_clicks
            450,  # landing_page_views
            40,  # add_to_carts
            10,  # purchases
            Decimal("500.00"),  # purchase_value
        )
        vs = _row_to_variant_summary(row)
        assert isinstance(vs, VariantSummary)
        assert vs.variant_id == variant_id
        assert vs.variant_code == "V1"
        assert vs.status == "active"
        assert vs.impressions == 10000
        assert vs.clicks == 500
        assert vs.purchases == 10
        # CTR = 500 / 10000 = 0.05
        assert vs.ctr == Decimal("0.05")
        # Cost per purchase = 200 / 10 = 20
        assert vs.cost_per_purchase == Decimal("20.0")
        # ROAS = 500 / 200 = 2.5
        assert vs.roas == Decimal("2.5")

    def test_zero_impressions_yields_zero_ctr(self):
        row = (
            uuid4(), "V2", "active",
            0, 0, 0, Decimal("0"),
            0, 0, 0, 0, 0, 0, 0, 0, Decimal("0"),
        )
        vs = _row_to_variant_summary(row)
        assert vs.ctr == Decimal("0")
        assert vs.cost_per_purchase is None
        assert vs.roas is None


# ---------------------------------------------------------------------------
# _variant_summary_to_variant_report
# ---------------------------------------------------------------------------


def _make_variant_summary(**overrides) -> VariantSummary:
    variant_id = overrides.pop("variant_id", uuid4())
    defaults: dict = dict(
        variant_id=variant_id,
        variant_code="V1",
        status="active",
        impressions=10000,
        clicks=500,
        conversions=50,
        spend=Decimal("200.00"),
        ctr=Decimal("0.05"),
        cpa=Decimal("4.0"),
        reach=8000,
        video_views_3s=3500,
        video_views_15s=1200,
        thruplays=800,
        link_clicks=500,
        landing_page_views=450,
        add_to_carts=40,
        purchases=10,
        purchase_value=Decimal("500.00"),
        hook_rate=Decimal("0.35"),
        hold_rate=Decimal("0.343"),
        cost_per_purchase=Decimal("20.00"),
        roas=Decimal("2.5"),
    )
    defaults.update(overrides)
    return VariantSummary(**defaults)


class TestVariantSummaryToVariantReport:
    def test_rate_conversions_are_correct_percentages(self):
        vs = _make_variant_summary()
        vr = _variant_summary_to_variant_report(vs, genome_map={})
        # 3500 / 10000 * 100 = 35
        assert vr.hook_rate_pct == 35.0
        # 1200 / 3500 * 100 ≈ 34.28
        assert round(vr.hold_rate_pct, 2) == 34.29
        # 500 / 10000 * 100 = 5
        assert vr.ctr_pct == 5.0
        # 40 / 500 * 100 = 8
        assert vr.atc_rate_pct == 8.0
        # 10 / 40 * 100 = 25
        assert vr.checkout_rate_pct == 25.0
        # 10000 / 8000 = 1.25
        assert vr.frequency == 1.25

    def test_genome_enrichment(self):
        vs = _make_variant_summary()
        genome_map = {
            str(vs.variant_id): {
                "genome": {
                    "headline": "Limited time: 40% off today only",
                    "cta_text": "Claim my discount",
                },
                "hypothesis": "Urgency drives conversion",
                "days_active": 7,
            }
        }
        vr = _variant_summary_to_variant_report(vs, genome_map)
        assert vr.genome["headline"] == "Limited time: 40% off today only"
        assert vr.hypothesis == "Urgency drives conversion"
        assert vr.days_active == 7
        # Genome summary truncates headline to 30 chars and joins with CTA
        assert "Claim my discount" in vr.genome_summary

    def test_missing_genome_falls_back_to_variant_code(self):
        vs = _make_variant_summary(variant_code="V42")
        vr = _variant_summary_to_variant_report(vs, genome_map={})
        assert vr.genome == {}
        assert vr.hypothesis is None
        assert vr.days_active == 1
        assert vr.genome_summary == "V42"

    def test_zero_denominators_do_not_crash(self):
        vs = _make_variant_summary(
            impressions=0,
            video_views_3s=0,
            video_views_15s=0,
            link_clicks=0,
            add_to_carts=0,
            purchases=0,
            reach=0,
            cost_per_purchase=None,
            roas=None,
        )
        vr = _variant_summary_to_variant_report(vs, genome_map={})
        assert vr.hook_rate_pct == 0.0
        assert vr.hold_rate_pct == 0.0
        assert vr.ctr_pct == 0.0
        assert vr.atc_rate_pct == 0.0
        assert vr.checkout_rate_pct == 0.0
        assert vr.frequency == 0.0
        assert vr.cost_per_purchase is None
        assert vr.roas is None


# ---------------------------------------------------------------------------
# Public API smoke test with a fake AsyncSession
# ---------------------------------------------------------------------------


class _FakeResult:
    """Mimic the SQLAlchemy ``Result`` surface used by the service."""

    def __init__(self, rows: list):
        self._rows = rows

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def fetchall(self):
        return self._rows

    def scalar_one(self):
        return self._rows[0][0] if self._rows else 0


class _FakeSession:
    """Return canned rows keyed by a snippet of the SQL text.

    Each test sets up ``self.results`` as a list of tuples
    ``(snippet, fake_result)``; the first snippet matched wins. This keeps the
    tests readable — we're asserting the composition logic, not the SQL.
    """

    def __init__(self, results):
        self.results = results
        self.calls: list[str] = []

    async def execute(self, query, params=None):  # noqa: ARG002
        sql = str(query)
        self.calls.append(sql)
        for snippet, result in self.results:
            if snippet in sql:
                return result
        raise AssertionError(f"Unexpected query: {sql!r}")


@pytest.fixture()
def campaign_id() -> UUID:
    return UUID("daddba0e-0000-0000-0000-000000000000")


class TestBuildDailyReport:
    @pytest.mark.asyncio
    async def test_empty_campaign_returns_empty_daily_report(self, campaign_id):
        session = _FakeSession([
            ("FROM campaigns WHERE id", _FakeResult([("Test Campaign",)])),
            ("FROM test_cycles", _FakeResult([])),
            # Aggregate metrics — all zeros
            (
                "FROM metrics m\n            JOIN variants v",
                _FakeResult([(0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0)]),
            ),
            # Variant leaderboard — empty
            ("FROM variants v\n            LEFT JOIN LATERAL", _FakeResult([])),
            # Genome map — empty
            (
                "FROM variants v\n            WHERE v.campaign_id = :id AND v.status IN",
                _FakeResult([]),
            ),
            # Previous day totals — all zeros
            ("COALESCE(SUM(m.spend), 0)", _FakeResult([(0, 0, 0)])),
        ])

        report = await build_daily_report(session, campaign_id, date(2026, 4, 8))
        assert report.campaign_name == "Test Campaign"
        assert report.total_spend == Decimal("0")
        assert report.total_purchases == 0
        assert report.variants == []
        assert report.best_variant is None
        assert report.best_variant_funnel == []
        assert report.best_variant_diagnostics == []

    @pytest.mark.asyncio
    async def test_missing_campaign_raises_lookup_error(self, campaign_id):
        session = _FakeSession([
            ("FROM campaigns WHERE id", _FakeResult([])),
        ])
        with pytest.raises(LookupError):
            await build_daily_report(session, campaign_id, date(2026, 4, 8))


class TestBuildWeeklyReport:
    @pytest.mark.asyncio
    async def test_empty_campaign_returns_empty_weekly_report(
        self, campaign_id, monkeypatch
    ):
        # ``load_proposed_variants`` is imported at module load time, so patch
        # the reference on the service module.
        from src.services import reports as reports_module

        async def _fake_load_proposed_variants(session, cid):
            return []

        monkeypatch.setattr(
            reports_module, "load_proposed_variants", _fake_load_proposed_variants
        )

        session = _FakeSession([
            ("FROM campaigns WHERE id", _FakeResult([("Test Campaign",)])),
            ("FROM test_cycles", _FakeResult([])),
            (
                "FROM metrics m\n            JOIN variants v",
                _FakeResult([(0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0)]),
            ),
            ("FROM variants v\n            LEFT JOIN LATERAL", _FakeResult([])),
            ("FROM element_performance", _FakeResult([])),
            ("FROM element_interactions", _FakeResult([])),
        ])

        report = await build_weekly_report(
            session,
            campaign_id,
            date(2026, 3, 30),
            week_end=date(2026, 4, 5),
        )
        assert report.campaign_name == "Test Campaign"
        assert report.week_start == date(2026, 3, 30)
        assert report.week_end == date(2026, 4, 5)
        assert report.total_spend == Decimal("0")
        assert report.all_variants == []
        assert report.top_elements == []
        assert report.top_interactions == []
        assert report.proposed_variants == []
        assert report.cycles_run == 0
        assert report.expired_count == 0
        assert report.generation_paused is False
        assert report.review_url is None

    @pytest.mark.asyncio
    async def test_passes_through_generation_side_effects(
        self, campaign_id, monkeypatch
    ):
        from src.services import reports as reports_module

        async def _fake_load_proposed_variants(session, cid):
            return []

        monkeypatch.setattr(
            reports_module, "load_proposed_variants", _fake_load_proposed_variants
        )

        session = _FakeSession([
            ("FROM campaigns WHERE id", _FakeResult([("Test Campaign",)])),
            ("FROM test_cycles", _FakeResult([])),
            (
                "FROM metrics m\n            JOIN variants v",
                _FakeResult([(0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0)]),
            ),
            ("FROM variants v\n            LEFT JOIN LATERAL", _FakeResult([])),
            ("FROM element_performance", _FakeResult([])),
            ("FROM element_interactions", _FakeResult([])),
        ])

        report = await build_weekly_report(
            session,
            campaign_id,
            date(2026, 3, 30),
            expired_count=3,
            generation_paused=True,
            review_url="https://example.com/review/abc",
        )
        assert report.expired_count == 3
        assert report.generation_paused is True
        assert report.review_url == "https://example.com/review/abc"
