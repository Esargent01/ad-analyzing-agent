"""Tests for per-objective profile dispatch and display-list builders.

These tests pin the objective-to-display mapping so the email and
React renderers can rely on shape invariants: every profile has 4
daily headline cards, every weekly profile has 3 rows of 4 cards,
the best-variant ranker picks the right variant per objective, and
unknown / deferred values fall back to Sales.
"""

from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import pytest

from src.adapters.meta_objective import ODAX_VALUES
from src.services.objectives import (
    OBJECTIVES,
    build_diagnostic_tiles,
    build_headline_metrics,
    build_summary_numbers,
    build_variant_table_columns,
    format_value,
    profile_for,
)


# ---------------------------------------------------------------------------
# Profile registry
# ---------------------------------------------------------------------------


class TestProfileRegistry:
    """Registry should hold 5 fully-supported profiles (App Promotion
    deferred) and fall back to Sales for unknowns."""

    def test_five_in_scope_objectives_registered(self) -> None:
        assert set(OBJECTIVES.keys()) == {
            "OUTCOME_SALES",
            "OUTCOME_LEADS",
            "OUTCOME_ENGAGEMENT",
            "OUTCOME_TRAFFIC",
            "OUTCOME_AWARENESS",
        }

    @pytest.mark.parametrize("objective", sorted(OBJECTIVES.keys()))
    def test_profile_shape_invariants(self, objective: str) -> None:
        """Every profile must have:
          - exactly 4 daily headline cards
          - exactly 3 weekly rows of 4 cards each
          - exactly 3 summary numbers
          - exactly 3 image + 3 video diagnostic tiles
          - at least 2 funnel stages
        """
        p = OBJECTIVES[objective]
        assert len(p.daily_headline_specs) == 4
        assert len(p.weekly_row_specs) == 3
        for row in p.weekly_row_specs:
            assert len(row) == 4
        assert len(p.weekly_row_titles) == 3
        assert len(p.summary_specs) == 3
        assert len(p.image_diagnostic_specs) == 3
        assert len(p.video_diagnostic_specs) == 3
        assert len(p.funnel_stage_keys) >= 2
        assert len(p.variant_col_specs) >= 2

    @pytest.mark.parametrize(
        "objective",
        [
            "OUTCOME_APP_PROMOTION",  # deferred
            "OUTCOME_UNKNOWN",
            "GARBAGE",
            None,
            "",
        ],
    )
    def test_unknown_falls_back_to_sales(self, objective: str | None) -> None:
        assert profile_for(objective).canonical == "OUTCOME_SALES"


# ---------------------------------------------------------------------------
# Best-variant rankers
# ---------------------------------------------------------------------------


def _variant(**overrides: object) -> object:
    """Build a minimal VariantReport-like object for ranker tests."""
    base: dict[str, object] = {
        "variant_id": uuid4(),
        "variant_code": "V1",
        "spend": Decimal("10.00"),
        "cost_per_purchase": 20.0,
        "purchases": 5,
        "roas": 2.0,
        "cost_per_lead": 25.0,
        "leads": 3,
        "post_engagements": 50,
        "cost_per_engagement": 0.5,
        "cpc": 0.75,
        "cpm": 8.0,
        "reach": 1000,
        "frequency": 1.5,
        "impressions": 1500,
        "link_clicks": 40,
        "ctr_pct": 2.6,
        "media_type": "image",
    }
    base.update(overrides)
    return SimpleNamespace(**base)


class TestBestVariantRankers:
    def test_sales_ranker_picks_lowest_cpa(self) -> None:
        v1 = _variant(variant_code="V1", cost_per_purchase=30.0, spend=Decimal("100"))
        v2 = _variant(variant_code="V2", cost_per_purchase=15.0, spend=Decimal("100"))
        v3 = _variant(variant_code="V3", cost_per_purchase=None, spend=Decimal("0"))
        picked = OBJECTIVES["OUTCOME_SALES"].best_variant_ranker([v1, v2, v3])
        assert picked is v2

    def test_sales_ranker_returns_none_when_no_purchases(self) -> None:
        v1 = _variant(cost_per_purchase=None, spend=Decimal("10"))
        v2 = _variant(cost_per_purchase=None, spend=Decimal("20"))
        assert OBJECTIVES["OUTCOME_SALES"].best_variant_ranker([v1, v2]) is None

    def test_leads_ranker_picks_lowest_cpl(self) -> None:
        v1 = _variant(variant_code="V1", cost_per_lead=35.0)
        v2 = _variant(variant_code="V2", cost_per_lead=18.0)
        picked = OBJECTIVES["OUTCOME_LEADS"].best_variant_ranker([v1, v2])
        assert picked is v2

    def test_engagement_ranker_picks_most_engagements(self) -> None:
        v1 = _variant(variant_code="V1", post_engagements=200)
        v2 = _variant(variant_code="V2", post_engagements=50)
        picked = OBJECTIVES["OUTCOME_ENGAGEMENT"].best_variant_ranker([v1, v2])
        assert picked is v1

    def test_engagement_ranker_returns_none_on_zero_engagements(self) -> None:
        v1 = _variant(post_engagements=0)
        v2 = _variant(post_engagements=0)
        assert OBJECTIVES["OUTCOME_ENGAGEMENT"].best_variant_ranker([v1, v2]) is None

    def test_traffic_ranker_picks_lowest_cpc(self) -> None:
        v1 = _variant(variant_code="V1", cpc=1.20)
        v2 = _variant(variant_code="V2", cpc=0.55)
        picked = OBJECTIVES["OUTCOME_TRAFFIC"].best_variant_ranker([v1, v2])
        assert picked is v2

    def test_awareness_ranker_picks_lowest_cpm(self) -> None:
        v1 = _variant(variant_code="V1", cpm=14.0)
        v2 = _variant(variant_code="V2", cpm=7.5)
        picked = OBJECTIVES["OUTCOME_AWARENESS"].best_variant_ranker([v1, v2])
        assert picked is v2


# ---------------------------------------------------------------------------
# Formatter
# ---------------------------------------------------------------------------


class TestFormatter:
    @pytest.mark.parametrize(
        ("value", "fmt", "expected"),
        [
            (None, "currency", "—"),
            (12.34, "currency", "$12.34"),
            (1234.7, "currency", "$1,235"),
            (0, "currency", "$0.00"),
            (12345, "int_comma", "12,345"),
            (2.3, "pct", "2.3%"),
            (2.4, "roas", "2.4x"),
            (0, "roas", "N/A"),
            (12.34, "onedecimal", "12.3"),
        ],
    )
    def test_formats(self, value, fmt, expected) -> None:
        assert format_value(value, fmt) == expected


# ---------------------------------------------------------------------------
# Display-list builders
# ---------------------------------------------------------------------------


class TestHeadlineBuilder:
    def test_traffic_headline_labels_match_profile(self) -> None:
        totals = SimpleNamespace(
            total_spend=Decimal("100"),
            total_link_clicks=250,
            avg_cpc=0.40,
            avg_ctr=2.5,
            prev_spend=None,
            prev_link_clicks=None,
            prev_avg_cpc=None,
            prev_avg_ctr=None,
        )
        cards = build_headline_metrics(
            OBJECTIVES["OUTCOME_TRAFFIC"].daily_headline_specs, totals
        )
        assert [c.label for c in cards] == ["SPEND", "LINK CLICKS", "AVG CPC", "CTR"]
        assert cards[0].value == "$100.00"
        assert cards[1].value == "250"
        assert cards[2].value == "$0.40"
        assert cards[3].value == "2.5%"

    def test_empty_value_gets_fallback_sub(self) -> None:
        totals = SimpleNamespace(
            total_spend=Decimal("10"),
            total_purchases=0,
            avg_cost_per_purchase=None,
            avg_roas=None,
            prev_spend=None,
            prev_purchases=None,
            prev_avg_cpa=None,
            prev_avg_roas=None,
        )
        cards = build_headline_metrics(
            OBJECTIVES["OUTCOME_SALES"].daily_headline_specs, totals
        )
        cpa_card = next(c for c in cards if c.label == "AVG CPA")
        assert cpa_card.value == "—"
        assert cpa_card.sub == "no purchases"

    def test_tone_direction_up_is_better(self) -> None:
        # Purchases up is good.
        totals = SimpleNamespace(
            total_spend=Decimal("10"),
            total_purchases=10,
            avg_cost_per_purchase=None,
            avg_roas=None,
            prev_spend=None,
            prev_purchases=5,
            prev_avg_cpa=None,
            prev_avg_roas=None,
        )
        cards = build_headline_metrics(
            OBJECTIVES["OUTCOME_SALES"].daily_headline_specs, totals
        )
        purch_card = next(c for c in cards if c.label == "PURCHASES")
        assert purch_card.tone == "good"

    def test_tone_direction_down_is_better(self) -> None:
        # CPA down is good.
        totals = SimpleNamespace(
            total_spend=Decimal("10"),
            total_purchases=10,
            avg_cost_per_purchase=20.0,
            avg_roas=None,
            prev_spend=None,
            prev_purchases=None,
            prev_avg_cpa=30.0,
            prev_avg_roas=None,
        )
        cards = build_headline_metrics(
            OBJECTIVES["OUTCOME_SALES"].daily_headline_specs, totals
        )
        cpa_card = next(c for c in cards if c.label == "AVG CPA")
        assert cpa_card.tone == "good"


class TestSummaryBuilder:
    def test_sales_summary_shape(self) -> None:
        v = _variant(cost_per_purchase=25.0, roas=3.2, purchases=10)
        nums = build_summary_numbers(
            OBJECTIVES["OUTCOME_SALES"].summary_specs, v
        )
        assert [n.label for n in nums] == ["CPA", "ROAS", "PURCH"]
        assert nums[0].value == "$25.00"
        assert nums[1].value == "3.2x"
        assert nums[2].value == "10"

    def test_good_tone_drops_to_neutral_when_value_zero(self) -> None:
        # ROAS = 0 should not tint green.
        v = _variant(roas=0)
        nums = build_summary_numbers(
            OBJECTIVES["OUTCOME_SALES"].summary_specs, v
        )
        roas = next(n for n in nums if n.label == "ROAS")
        assert roas.tone == "neutral"


class TestDiagnosticTileBuilder:
    def test_good_tone_applied_when_benchmark_cleared(self) -> None:
        v = _variant(hook_rate_pct=35.0, hold_rate_pct=10.0, ctr_pct=2.0)
        tiles = build_diagnostic_tiles(
            OBJECTIVES["OUTCOME_SALES"].video_diagnostic_specs, v
        )
        # HOOK: 35 >= 30 → good
        assert tiles[0].label == "HOOK"
        assert tiles[0].tone == "good"
        # HOLD: 10 < 25 → neutral
        assert tiles[1].label == "HOLD"
        assert tiles[1].tone == "neutral"


class TestVariantTableColumns:
    def test_columns_match_profile(self) -> None:
        cols = build_variant_table_columns(
            OBJECTIVES["OUTCOME_LEADS"].variant_col_specs
        )
        assert [c.label for c in cols] == ["HOOK", "CTR", "CPL", "LEADS"]
        assert cols[2].key == "cost_per_lead"
        assert cols[0].image_em_dash is True


# ---------------------------------------------------------------------------
# ODAX coverage
# ---------------------------------------------------------------------------


class TestODAXCoverage:
    def test_odax_values_constant_includes_all_six(self) -> None:
        assert "OUTCOME_APP_PROMOTION" in ODAX_VALUES
        assert len(ODAX_VALUES) == 6
