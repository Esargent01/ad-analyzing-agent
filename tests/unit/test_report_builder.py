"""Tests for src.reports.builder — pure report-building functions."""

from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

from src.models.reports import VariantReport
from src.reports.builder import (
    build_diagnostics,
    build_funnel,
    build_projection,
    select_best_variant,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_DEFAULTS = dict(
    variant_id=uuid4(),
    variant_code="V1",
    genome={"headline": "Test headline", "cta_text": "Buy now"},
    genome_summary="test headline + buy now CTA",
    hypothesis="Test hypothesis",
    status="steady",
    days_active=5,
    spend=Decimal("100.00"),
    purchases=5,
    purchase_value=Decimal("250.00"),
    cost_per_purchase=20.0,
    roas=2.5,
    impressions=10000,
    reach=8000,
    video_views_3s=3500,
    video_views_15s=1200,
    link_clicks=500,
    landing_page_views=400,
    add_to_carts=40,
    hook_rate_pct=35.0,
    hold_rate_pct=34.3,
    ctr_pct=5.0,
    atc_rate_pct=8.0,
    checkout_rate_pct=12.5,
    frequency=1.8,
)


def _variant(**overrides) -> VariantReport:
    """Create a VariantReport with sensible defaults, overriding as needed."""
    return VariantReport(**{**_DEFAULTS, **overrides})


# ---------------------------------------------------------------------------
# build_funnel
# ---------------------------------------------------------------------------


class TestBuildFunnel:
    def test_stage_count(self):
        v = _variant()
        stages = build_funnel(v)
        assert len(stages) == 6

    def test_stage_labels(self):
        v = _variant()
        stages = build_funnel(v)
        labels = [s.label for s in stages]
        assert labels == [
            "Impressions",
            "3s views",
            "15s views",
            "Link clicks",
            "Add to carts",
            "Purchases",
        ]

    def test_stage_counts_match_variant(self):
        v = _variant()
        stages = build_funnel(v)
        assert stages[0].count == v.impressions
        assert stages[1].count == v.video_views_3s
        assert stages[2].count == v.video_views_15s
        assert stages[3].count == v.link_clicks
        assert stages[4].count == v.add_to_carts
        assert stages[5].count == v.purchases

    def test_first_stage_has_no_dropoff(self):
        v = _variant()
        stages = build_funnel(v)
        assert stages[0].dropoff_pct == 0.0

    def test_dropoff_is_proportional(self):
        v = _variant(impressions=1000, video_views_3s=500)
        stages = build_funnel(v)
        # 500 / 1000 = 50% dropoff
        assert stages[1].dropoff_pct == 50.0

    def test_colors_are_correct(self):
        v = _variant()
        stages = build_funnel(v)
        expected_colors = ["#534AB7", "#7F77DD", "#378ADD", "#1D9E75", "#639922", "#27500A"]
        assert [s.bar_color for s in stages] == expected_colors

    def test_rates_match_variant(self):
        v = _variant(hook_rate_pct=35.0, hold_rate_pct=34.3, ctr_pct=5.0)
        stages = build_funnel(v)
        assert stages[0].rate_pct == 100.0  # Impressions always 100%
        assert stages[1].rate_pct == 35.0
        assert stages[2].rate_pct == 34.3
        assert stages[3].rate_pct == 5.0

    def test_zero_impressions_no_crash(self):
        v = _variant(
            impressions=0,
            video_views_3s=0,
            video_views_15s=0,
            link_clicks=0,
            add_to_carts=0,
            purchases=0,
        )
        stages = build_funnel(v)
        assert len(stages) == 6
        # All dropoffs should be 0 when prev_count is 0
        for s in stages:
            assert s.dropoff_pct == 0.0


# ---------------------------------------------------------------------------
# build_diagnostics
# ---------------------------------------------------------------------------


class TestBuildDiagnostics:
    # Hook rate levels
    def test_hook_rate_good(self):
        diags = build_diagnostics(_variant(hook_rate_pct=35.0))
        hook = [d for d in diags if "Hook rate" in d.text]
        assert len(hook) == 1
        assert hook[0].severity == "good"

    def test_hook_rate_warning(self):
        diags = build_diagnostics(_variant(hook_rate_pct=27.0))
        hook = [d for d in diags if "Hook rate" in d.text]
        assert hook[0].severity == "warning"

    def test_hook_rate_bad(self):
        diags = build_diagnostics(_variant(hook_rate_pct=20.0))
        hook = [d for d in diags if "Hook rate" in d.text]
        assert hook[0].severity == "bad"

    # Hold rate levels
    def test_hold_rate_good(self):
        diags = build_diagnostics(_variant(hold_rate_pct=30.0))
        hold = [d for d in diags if "Hold rate" in d.text]
        assert hold[0].severity == "good"

    def test_hold_rate_warning(self):
        diags = build_diagnostics(_variant(hold_rate_pct=18.0))
        hold = [d for d in diags if "Hold rate" in d.text]
        assert hold[0].severity == "warning"

    def test_hold_rate_bad(self):
        diags = build_diagnostics(_variant(hold_rate_pct=10.0))
        hold = [d for d in diags if "Hold rate" in d.text]
        assert hold[0].severity == "bad"

    # ATC rate levels
    def test_atc_rate_good(self):
        diags = build_diagnostics(_variant(atc_rate_pct=7.0))
        atc = [d for d in diags if "ATC rate" in d.text]
        assert atc[0].severity == "good"

    def test_atc_rate_bad(self):
        diags = build_diagnostics(_variant(atc_rate_pct=3.0))
        atc = [d for d in diags if "ATC rate" in d.text]
        assert atc[0].severity == "bad"

    # Checkout rate levels
    def test_checkout_rate_good(self):
        diags = build_diagnostics(_variant(checkout_rate_pct=35.0))
        checkout = [d for d in diags if "Checkout rate" in d.text]
        assert checkout[0].severity == "good"

    def test_checkout_rate_warning(self):
        diags = build_diagnostics(_variant(checkout_rate_pct=25.0))
        checkout = [d for d in diags if "Checkout rate" in d.text]
        assert checkout[0].severity == "warning"

    def test_checkout_rate_bad(self):
        diags = build_diagnostics(_variant(checkout_rate_pct=10.0))
        checkout = [d for d in diags if "Checkout rate" in d.text]
        assert checkout[0].severity == "bad"

    def test_checkout_rate_zero_omitted(self):
        diags = build_diagnostics(_variant(checkout_rate_pct=0.0))
        checkout = [d for d in diags if "Checkout rate" in d.text]
        assert len(checkout) == 0

    # Frequency levels
    def test_frequency_high(self):
        diags = build_diagnostics(_variant(frequency=3.5))
        freq = [d for d in diags if "Frequency" in d.text]
        assert freq[0].severity == "bad"

    def test_frequency_warning(self):
        diags = build_diagnostics(_variant(frequency=2.7))
        freq = [d for d in diags if "Frequency" in d.text]
        assert freq[0].severity == "warning"

    def test_frequency_ok_omitted(self):
        diags = build_diagnostics(_variant(frequency=1.5))
        freq = [d for d in diags if "Frequency" in d.text]
        assert len(freq) == 0


# ---------------------------------------------------------------------------
# build_projection
# ---------------------------------------------------------------------------


class TestBuildProjection:
    def test_no_purchases_returns_none(self):
        result = build_projection(_variant(purchases=0, cost_per_purchase=None))
        assert result is None

    def test_all_above_benchmark_returns_none(self):
        result = build_projection(
            _variant(
                hook_rate_pct=35.0,
                hold_rate_pct=30.0,
                atc_rate_pct=12.0,
                checkout_rate_pct=35.0,
            )
        )
        assert result is None

    def test_checkout_rate_projection(self):
        # Checkout rate is 12.5%, benchmark is 30%. That's the weakest.
        # ATC rate is 8% vs 10% benchmark (20% gap).
        # Checkout rate: 12.5% vs 30% benchmark (58% gap) — weakest.
        v = _variant(
            checkout_rate_pct=12.5,
            add_to_carts=40,
            spend=Decimal("100.00"),
            cost_per_purchase=20.0,
            purchases=5,
            # Make other stages above benchmark
            hook_rate_pct=35.0,
            hold_rate_pct=30.0,
            atc_rate_pct=12.0,
        )
        result = build_projection(v)
        assert result is not None
        assert "checkout rate" in result
        assert "30%" in result
        assert "$" in result

    def test_atc_rate_projection(self):
        # ATC rate 3% vs benchmark 10% (70% gap), checkout 35% vs 30% (above).
        # Hook and hold above benchmarks.
        v = _variant(
            atc_rate_pct=3.0,
            checkout_rate_pct=35.0,
            hook_rate_pct=35.0,
            hold_rate_pct=30.0,
            link_clicks=500,
            spend=Decimal("100.00"),
            cost_per_purchase=20.0,
            purchases=5,
        )
        result = build_projection(v)
        assert result is not None
        assert "ATC rate" in result
        assert "10%" in result

    def test_projection_contains_dollar_amounts(self):
        v = _variant(checkout_rate_pct=10.0)
        result = build_projection(v)
        assert result is not None
        assert "$" in result


# ---------------------------------------------------------------------------
# select_best_variant
# ---------------------------------------------------------------------------


class TestSelectBestVariant:
    def test_empty_list_returns_none(self):
        assert select_best_variant([]) is None

    def test_single_variant_with_enough_purchases(self):
        v = _variant(purchases=5, cost_per_purchase=20.0)
        assert select_best_variant([v]) is v

    def test_picks_lowest_cpa(self):
        v1 = _variant(variant_code="V1", purchases=5, cost_per_purchase=25.0)
        v2 = _variant(variant_code="V2", purchases=4, cost_per_purchase=15.0)
        assert select_best_variant([v1, v2]) is v2

    def test_min_3_purchases_rule(self):
        v_good_cpa = _variant(variant_code="V1", purchases=2, cost_per_purchase=10.0)
        v_worse_cpa = _variant(variant_code="V2", purchases=5, cost_per_purchase=30.0)
        # V1 has better CPA but < 3 purchases, V2 should win
        result = select_best_variant([v_good_cpa, v_worse_cpa])
        assert result is v_worse_cpa

    def test_fallback_to_most_purchases_when_none_hit_threshold(self):
        v1 = _variant(variant_code="V1", purchases=2, cost_per_purchase=10.0)
        v2 = _variant(variant_code="V2", purchases=1, cost_per_purchase=50.0)
        # Neither has 3 purchases, fallback to lowest CPA among those with purchases
        result = select_best_variant([v1, v2])
        assert result is v1

    def test_fallback_to_most_impressions_when_no_purchases(self):
        v1 = _variant(variant_code="V1", purchases=0, cost_per_purchase=None, impressions=5000)
        v2 = _variant(variant_code="V2", purchases=0, cost_per_purchase=None, impressions=8000)
        result = select_best_variant([v1, v2])
        assert result is v2

    def test_roas_breaks_cpa_tie(self):
        v1 = _variant(variant_code="V1", purchases=5, cost_per_purchase=20.0, roas=3.0)
        v2 = _variant(variant_code="V2", purchases=5, cost_per_purchase=20.0, roas=5.0)
        # Same CPA, V2 has higher ROAS so should win (lower -(roas))
        result = select_best_variant([v1, v2])
        assert result is v2
