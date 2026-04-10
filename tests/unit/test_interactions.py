"""Tests for pairwise element interaction tracking."""

from __future__ import annotations

from src.services.interactions import InteractionResult, _canonicalize_pair, compute_interactions


class TestCanonicalOrdering:
    """Tests for the _canonicalize_pair helper."""

    def test_already_canonical(self) -> None:
        """Pair already in canonical order should be returned unchanged."""
        result = _canonicalize_pair("audience", "broad", "headline", "x")
        assert result == ("audience", "broad", "headline", "x")

    def test_swap_when_slot_a_greater(self) -> None:
        """When slot_a > slot_b, the pair should be swapped."""
        result = _canonicalize_pair("subhead", "test copy", "cta_text", "Learn more")
        assert result == ("cta_text", "Learn more", "subhead", "test copy")

    def test_same_slot_orders_by_value(self) -> None:
        """Same slot name -- should order by value alphabetically."""
        result = _canonicalize_pair("cta_text", "Shop now", "cta_text", "Learn more")
        assert result == ("cta_text", "Learn more", "cta_text", "Shop now")

    def test_same_slot_already_canonical(self) -> None:
        """Same slot, values already in order."""
        result = _canonicalize_pair("cta_text", "Get started", "cta_text", "Learn more")
        assert result == ("cta_text", "Get started", "cta_text", "Learn more")


class TestComputeInteractions:
    """Tests for compute_interactions()."""

    def test_empty_input_returns_empty(self) -> None:
        """No variants means no interactions."""
        assert compute_interactions([]) == []

    def test_known_synergy_positive_lift(self) -> None:
        """Elements that perform better together should have positive lift.

        Setup: "Learn more" CTA + retargeting audience performs better together (5%)
        than "Learn more" alone (3%) or retargeting alone (3%).
        """
        variants = [
            # Has both Learn more + retargeting -- high CTR
            ({"cta_text": "Learn more", "audience": "retargeting_30d"}, 0.05),
            ({"cta_text": "Learn more", "audience": "retargeting_30d"}, 0.05),
            # Has Learn more but NOT retargeting
            ({"cta_text": "Learn more", "audience": "broad"}, 0.03),
            # Has retargeting but NOT Learn more
            ({"cta_text": "Get started free", "audience": "retargeting_30d"}, 0.03),
        ]

        results = compute_interactions(variants, min_combined_variants=2)

        # Find the Learn more + retargeting interaction
        pair = _find_interaction(results, "cta_text", "Learn more", "audience", "retargeting_30d")
        assert pair is not None
        assert pair.lift > 0  # synergy
        # Lift = 0.05 / max(0.03, 0.03) - 1 = 0.667
        assert abs(pair.lift - (0.05 / 0.03 - 1)) < 0.01

    def test_known_conflict_negative_lift(self) -> None:
        """Elements that perform worse together should have negative lift.

        Setup: "Shop now" CTA + broad audience performs worse together (1%)
        than "Shop now" alone (4%) or broad alone (4%).
        """
        variants = [
            # Has both Shop now + broad -- low CTR
            ({"cta_text": "Shop now", "audience": "broad"}, 0.01),
            ({"cta_text": "Shop now", "audience": "broad"}, 0.01),
            # Has Shop now but NOT broad
            ({"cta_text": "Shop now", "audience": "retargeting_30d"}, 0.04),
            # Has broad but NOT Shop now
            ({"cta_text": "Learn more", "audience": "broad"}, 0.04),
        ]

        results = compute_interactions(variants, min_combined_variants=2)

        pair = _find_interaction(results, "cta_text", "Shop now", "audience", "broad")
        assert pair is not None
        assert pair.lift < 0  # conflict
        # Lift = 0.01 / max(0.04, 0.04) - 1 = -0.75
        assert abs(pair.lift - (0.01 / 0.04 - 1)) < 0.01

    def test_minimum_variants_threshold(self) -> None:
        """Pairs with fewer than min_combined_variants should be excluded."""
        variants = [
            # Only 1 variant with both -- below threshold of 2
            ({"cta_text": "Learn more", "audience": "retargeting_30d"}, 0.05),
            ({"cta_text": "Learn more", "audience": "broad"}, 0.03),
            ({"cta_text": "Get started free", "audience": "retargeting_30d"}, 0.03),
        ]

        results = compute_interactions(variants, min_combined_variants=2)
        pair = _find_interaction(results, "cta_text", "Learn more", "audience", "retargeting_30d")
        assert pair is None  # excluded due to threshold

    def test_canonical_ordering_in_results(self) -> None:
        """All results should have slot_a_name <= slot_b_name."""
        variants = [
            ({"audience": "retargeting_30d", "cta_text": "Learn more"}, 0.05),
            ({"audience": "retargeting_30d", "cta_text": "Learn more"}, 0.05),
            ({"audience": "broad", "cta_text": "Learn more"}, 0.03),
            ({"audience": "retargeting_30d", "cta_text": "Get started free"}, 0.03),
        ]

        results = compute_interactions(variants, min_combined_variants=2)
        for r in results:
            assert r.slot_a_name <= r.slot_b_name, (
                f"Non-canonical ordering: {r.slot_a_name} > {r.slot_b_name}"
            )

    def test_results_sorted_by_absolute_lift(self) -> None:
        """Results should be sorted by absolute lift descending."""
        variants = [
            ({"cta_text": "Learn more", "audience": "retargeting_30d"}, 0.05),
            ({"cta_text": "Learn more", "audience": "retargeting_30d"}, 0.05),
            ({"cta_text": "Learn more", "audience": "broad"}, 0.03),
            ({"cta_text": "Get started free", "audience": "retargeting_30d"}, 0.03),
            ({"cta_text": "Get started free", "audience": "broad"}, 0.04),
            ({"cta_text": "Get started free", "audience": "broad"}, 0.04),
            ({"cta_text": "Learn more", "audience": "broad"}, 0.03),
            ({"cta_text": "Get started free", "audience": "retargeting_30d"}, 0.03),
        ]

        results = compute_interactions(variants, min_combined_variants=2)
        lifts = [abs(r.lift) for r in results]
        assert lifts == sorted(lifts, reverse=True)

    def test_no_solo_data_excluded(self) -> None:
        """If there's no solo data for one element, the pair should be excluded."""
        # All variants have both elements -- no solo data
        variants = [
            ({"cta_text": "Learn more", "audience": "retargeting_30d"}, 0.05),
            ({"cta_text": "Learn more", "audience": "retargeting_30d"}, 0.04),
        ]
        results = compute_interactions(variants, min_combined_variants=2)
        # Should be empty because there's no variant with Learn more but not retargeting
        pair = _find_interaction(results, "cta_text", "Learn more", "audience", "retargeting_30d")
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
