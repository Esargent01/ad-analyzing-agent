"""Tests for pairwise element interaction tracking."""

from __future__ import annotations

import pytest

from src.services.interactions import InteractionResult, _canonicalize_pair, compute_interactions


class TestCanonicalOrdering:
    """Tests for the _canonicalize_pair helper."""

    def test_already_canonical(self) -> None:
        """Pair already in canonical order should be returned unchanged."""
        result = _canonicalize_pair("audience", "broad", "headline", "x")
        assert result == ("audience", "broad", "headline", "x")

    def test_swap_when_slot_a_greater(self) -> None:
        """When slot_a > slot_b, the pair should be swapped."""
        result = _canonicalize_pair("urgency", "time_limited", "cta_color", "green")
        assert result == ("cta_color", "green", "urgency", "time_limited")

    def test_same_slot_orders_by_value(self) -> None:
        """Same slot name -- should order by value alphabetically."""
        result = _canonicalize_pair("cta_color", "orange", "cta_color", "blue")
        assert result == ("cta_color", "blue", "cta_color", "orange")

    def test_same_slot_already_canonical(self) -> None:
        """Same slot, values already in order."""
        result = _canonicalize_pair("cta_color", "blue", "cta_color", "green")
        assert result == ("cta_color", "blue", "cta_color", "green")


class TestComputeInteractions:
    """Tests for compute_interactions()."""

    def test_empty_input_returns_empty(self) -> None:
        """No variants means no interactions."""
        assert compute_interactions([]) == []

    def test_known_synergy_positive_lift(self) -> None:
        """Elements that perform better together should have positive lift.

        Setup: green CTA + time_limited urgency performs better together (5%)
        than green CTA alone (3%) or time_limited alone (3%).
        """
        variants = [
            # Has both green + time_limited -- high CTR
            ({"cta_color": "green", "urgency": "time_limited"}, 0.05),
            ({"cta_color": "green", "urgency": "time_limited"}, 0.05),
            # Has green but NOT time_limited
            ({"cta_color": "green", "urgency": "none"}, 0.03),
            # Has time_limited but NOT green
            ({"cta_color": "blue", "urgency": "time_limited"}, 0.03),
        ]

        results = compute_interactions(variants, min_combined_variants=2)

        # Find the green + time_limited interaction
        pair = _find_interaction(results, "cta_color", "green", "urgency", "time_limited")
        assert pair is not None
        assert pair.lift > 0  # synergy
        # Lift = 0.05 / max(0.03, 0.03) - 1 = 0.667
        assert abs(pair.lift - (0.05 / 0.03 - 1)) < 0.01

    def test_known_conflict_negative_lift(self) -> None:
        """Elements that perform worse together should have negative lift.

        Setup: orange CTA + stock_limited urgency performs worse together (1%)
        than orange alone (4%) or stock_limited alone (4%).
        """
        variants = [
            # Has both orange + stock_limited -- low CTR
            ({"cta_color": "orange", "urgency": "stock_limited"}, 0.01),
            ({"cta_color": "orange", "urgency": "stock_limited"}, 0.01),
            # Has orange but NOT stock_limited
            ({"cta_color": "orange", "urgency": "none"}, 0.04),
            # Has stock_limited but NOT orange
            ({"cta_color": "blue", "urgency": "stock_limited"}, 0.04),
        ]

        results = compute_interactions(variants, min_combined_variants=2)

        pair = _find_interaction(results, "cta_color", "orange", "urgency", "stock_limited")
        assert pair is not None
        assert pair.lift < 0  # conflict
        # Lift = 0.01 / max(0.04, 0.04) - 1 = -0.75
        assert abs(pair.lift - (0.01 / 0.04 - 1)) < 0.01

    def test_minimum_variants_threshold(self) -> None:
        """Pairs with fewer than min_combined_variants should be excluded."""
        variants = [
            # Only 1 variant with both -- below threshold of 2
            ({"cta_color": "green", "urgency": "time_limited"}, 0.05),
            ({"cta_color": "green", "urgency": "none"}, 0.03),
            ({"cta_color": "blue", "urgency": "time_limited"}, 0.03),
        ]

        results = compute_interactions(variants, min_combined_variants=2)
        pair = _find_interaction(results, "cta_color", "green", "urgency", "time_limited")
        assert pair is None  # excluded due to threshold

    def test_canonical_ordering_in_results(self) -> None:
        """All results should have slot_a_name <= slot_b_name."""
        variants = [
            ({"urgency": "time_limited", "cta_color": "green"}, 0.05),
            ({"urgency": "time_limited", "cta_color": "green"}, 0.05),
            ({"urgency": "none", "cta_color": "green"}, 0.03),
            ({"urgency": "time_limited", "cta_color": "blue"}, 0.03),
        ]

        results = compute_interactions(variants, min_combined_variants=2)
        for r in results:
            assert r.slot_a_name <= r.slot_b_name, (
                f"Non-canonical ordering: {r.slot_a_name} > {r.slot_b_name}"
            )

    def test_results_sorted_by_absolute_lift(self) -> None:
        """Results should be sorted by absolute lift descending."""
        variants = [
            ({"cta_color": "green", "urgency": "time_limited"}, 0.05),
            ({"cta_color": "green", "urgency": "time_limited"}, 0.05),
            ({"cta_color": "green", "urgency": "none"}, 0.03),
            ({"cta_color": "blue", "urgency": "time_limited"}, 0.03),
            ({"cta_color": "blue", "urgency": "none"}, 0.04),
            ({"cta_color": "blue", "urgency": "none"}, 0.04),
            ({"cta_color": "green", "urgency": "none"}, 0.03),
            ({"cta_color": "blue", "urgency": "time_limited"}, 0.03),
        ]

        results = compute_interactions(variants, min_combined_variants=2)
        lifts = [abs(r.lift) for r in results]
        assert lifts == sorted(lifts, reverse=True)

    def test_no_solo_data_excluded(self) -> None:
        """If there's no solo data for one element, the pair should be excluded."""
        # All variants have both elements -- no solo data
        variants = [
            ({"cta_color": "green", "urgency": "time_limited"}, 0.05),
            ({"cta_color": "green", "urgency": "time_limited"}, 0.04),
        ]
        results = compute_interactions(variants, min_combined_variants=2)
        # Should be empty because there's no variant with green but not time_limited
        pair = _find_interaction(results, "cta_color", "green", "urgency", "time_limited")
        assert pair is None


def _find_interaction(
    results: list[InteractionResult],
    slot_a: str,
    val_a: str,
    slot_b: str,
    val_b: str,
) -> InteractionResult | None:
    """Find a specific interaction by its element pair (handles canonical ordering)."""
    ca, va, cb, vb = _canonicalize_pair(slot_a, val_a, slot_b, val_b)
    for r in results:
        if (
            r.slot_a_name == ca
            and r.slot_a_value == va
            and r.slot_b_name == cb
            and r.slot_b_value == vb
        ):
            return r
    return None
