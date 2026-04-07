"""Tests for the statistical significance functions in services.stats."""

from __future__ import annotations

import pytest

from src.services.stats import compare_variants, element_significance, has_sufficient_data


class TestCompareVariants:
    """Two-proportion z-test for variant CTR comparison."""

    def test_clearly_better_variant_is_significant(self) -> None:
        """A variant with dramatically higher CTR should be significant."""
        # Baseline: 2% CTR (200 clicks / 10000 impressions)
        # Variant:  5% CTR (500 clicks / 10000 impressions)
        z_score, p_value, is_significant = compare_variants(
            baseline_clicks=200,
            baseline_impressions=10_000,
            variant_clicks=500,
            variant_impressions=10_000,
            confidence_threshold=0.95,
        )
        assert is_significant is True
        assert p_value < 0.05
        assert z_score > 0  # variant is better

    def test_clearly_worse_variant_is_significant(self) -> None:
        """A variant with dramatically lower CTR should also be significant."""
        # Baseline: 5% CTR
        # Variant:  1% CTR
        z_score, p_value, is_significant = compare_variants(
            baseline_clicks=500,
            baseline_impressions=10_000,
            variant_clicks=100,
            variant_impressions=10_000,
            confidence_threshold=0.95,
        )
        assert is_significant is True
        assert p_value < 0.05
        assert z_score < 0  # variant is worse

    def test_no_real_difference_is_not_significant(self) -> None:
        """Two nearly identical CTRs should not be flagged as significant."""
        # Both at ~3% CTR with moderate sample
        z_score, p_value, is_significant = compare_variants(
            baseline_clicks=30,
            baseline_impressions=1000,
            variant_clicks=31,
            variant_impressions=1000,
            confidence_threshold=0.95,
        )
        assert is_significant is False
        assert p_value > 0.05

    def test_zero_baseline_impressions_not_significant(self) -> None:
        """Zero impressions on baseline should return not significant."""
        z_score, p_value, is_significant = compare_variants(
            baseline_clicks=0,
            baseline_impressions=0,
            variant_clicks=50,
            variant_impressions=1000,
        )
        assert is_significant is False
        assert p_value == 1.0
        assert z_score == 0.0

    def test_zero_variant_impressions_not_significant(self) -> None:
        """Zero impressions on variant should return not significant."""
        z_score, p_value, is_significant = compare_variants(
            baseline_clicks=50,
            baseline_impressions=1000,
            variant_clicks=0,
            variant_impressions=0,
        )
        assert is_significant is False
        assert p_value == 1.0

    def test_both_zero_clicks_not_significant(self) -> None:
        """Both having zero clicks (0% CTR) should not be significant."""
        z_score, p_value, is_significant = compare_variants(
            baseline_clicks=0,
            baseline_impressions=1000,
            variant_clicks=0,
            variant_impressions=1000,
        )
        assert is_significant is False
        # SE is zero when pooled proportion is zero
        assert p_value == 1.0

    def test_p_value_is_two_tailed(self) -> None:
        """The test should produce two-tailed p-values."""
        # Symmetric difference should give identical p-values regardless
        # of which variant is the baseline.
        _, p1, _ = compare_variants(
            baseline_clicks=200,
            baseline_impressions=10_000,
            variant_clicks=400,
            variant_impressions=10_000,
        )
        _, p2, _ = compare_variants(
            baseline_clicks=400,
            baseline_impressions=10_000,
            variant_clicks=200,
            variant_impressions=10_000,
        )
        assert abs(p1 - p2) < 1e-10

    def test_stricter_confidence_threshold(self) -> None:
        """A high confidence threshold (0.99) should be harder to pass."""
        # Moderate difference that passes 0.95 but may not pass 0.99
        _, _, sig_95 = compare_variants(
            baseline_clicks=100,
            baseline_impressions=5000,
            variant_clicks=130,
            variant_impressions=5000,
            confidence_threshold=0.95,
        )
        _, _, sig_99 = compare_variants(
            baseline_clicks=100,
            baseline_impressions=5000,
            variant_clicks=130,
            variant_impressions=5000,
            confidence_threshold=0.99,
        )
        # If it passes at 0.99, it must also pass at 0.95
        if sig_99:
            assert sig_95


class TestElementSignificance:
    """One-sample t-test for element performance vs. global mean."""

    def test_significantly_above_mean(self) -> None:
        """An element with CTRs well above the mean should have high confidence."""
        # Element CTRs all around 0.05, global mean 0.02
        t_stat, p_value, confidence = element_significance(
            element_ctrs=[0.048, 0.052, 0.050, 0.049, 0.051],
            global_mean_ctr=0.02,
        )
        assert t_stat > 0
        assert p_value < 0.05
        assert confidence > 95.0

    def test_at_mean_not_significant(self) -> None:
        """An element performing at the global mean should not be significant."""
        t_stat, p_value, confidence = element_significance(
            element_ctrs=[0.030, 0.031, 0.029, 0.030, 0.031],
            global_mean_ctr=0.03,
        )
        assert p_value > 0.05
        assert confidence < 95.0

    def test_single_observation_returns_defaults(self) -> None:
        """Fewer than 2 observations should return the safe default."""
        t_stat, p_value, confidence = element_significance(
            element_ctrs=[0.05],
            global_mean_ctr=0.03,
        )
        assert t_stat == 0.0
        assert p_value == 1.0
        assert confidence == 0.0

    def test_empty_list_returns_defaults(self) -> None:
        """Empty input should return the safe default."""
        t_stat, p_value, confidence = element_significance(
            element_ctrs=[],
            global_mean_ctr=0.03,
        )
        assert t_stat == 0.0
        assert p_value == 1.0
        assert confidence == 0.0

    def test_identical_observations_handle_nan(self) -> None:
        """Identical CTR values produce NaN in scipy -- should be handled gracefully."""
        t_stat, p_value, confidence = element_significance(
            element_ctrs=[0.03, 0.03, 0.03],
            global_mean_ctr=0.03,
        )
        # No variance, so t-test is degenerate
        assert t_stat == 0.0
        assert p_value == 1.0
        assert confidence == 0.0


class TestHasSufficientData:
    """Boundary tests for the minimum-data check."""

    def test_at_minimum_is_sufficient(self) -> None:
        assert has_sufficient_data(1000) is True

    def test_above_minimum_is_sufficient(self) -> None:
        assert has_sufficient_data(5000) is True

    def test_below_minimum_is_not_sufficient(self) -> None:
        assert has_sufficient_data(999) is False

    def test_zero_is_not_sufficient(self) -> None:
        assert has_sufficient_data(0) is False

    def test_custom_minimum(self) -> None:
        assert has_sufficient_data(500, min_required=500) is True
        assert has_sufficient_data(499, min_required=500) is False
