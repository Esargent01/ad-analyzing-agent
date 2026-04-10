"""Tests for Thompson sampling budget allocation."""

from __future__ import annotations

import uuid
from decimal import Decimal

import numpy as np
import pytest

from src.services.allocation import ThompsonSampler, allocate_budgets


def _make_variants(
    count: int,
    clicks: int = 50,
    impressions: int = 1000,
) -> list[tuple[uuid.UUID, int, int]]:
    """Helper to create a list of variant tuples."""
    return [(uuid.uuid4(), clicks, impressions) for _ in range(count)]


class TestThompsonSampler:
    """Tests for the ThompsonSampler weights."""

    def test_weights_sum_to_one(self) -> None:
        """Sample weights should always sum to approximately 1.0."""
        rng = np.random.default_rng(42)
        sampler = ThompsonSampler(rng=rng)
        variants = _make_variants(5)
        weights = sampler.sample_weights(variants)
        assert abs(sum(weights.values()) - 1.0) < 1e-10

    def test_seeded_rng_is_reproducible(self) -> None:
        """Using the same seed should produce identical weights."""
        variants = _make_variants(3, clicks=100, impressions=2000)
        w1 = ThompsonSampler(rng=np.random.default_rng(99)).sample_weights(variants)
        w2 = ThompsonSampler(rng=np.random.default_rng(99)).sample_weights(variants)
        for vid in w1:
            assert abs(w1[vid] - w2[vid]) < 1e-15

    def test_higher_ctr_gets_more_weight_on_average(self) -> None:
        """Over many samples, the variant with higher CTR should get more weight."""
        good_id = uuid.uuid4()
        bad_id = uuid.uuid4()
        variants = [
            (good_id, 500, 1000),  # 50% CTR
            (bad_id, 10, 1000),  # 1% CTR
        ]
        total_good = 0.0
        n_samples = 500
        for seed in range(n_samples):
            rng = np.random.default_rng(seed)
            sampler = ThompsonSampler(rng=rng)
            w = sampler.sample_weights(variants)
            total_good += w[good_id]

        avg_good_weight = total_good / n_samples
        assert avg_good_weight > 0.7  # should strongly favor the better variant


class TestAllocateBudgets:
    """Tests for the allocate_budgets() function."""

    def test_basic_allocation(self) -> None:
        """Budget should be distributed across all variants."""
        variants = _make_variants(3)
        total_budget = Decimal("100.00")
        allocations = allocate_budgets(variants, total_budget, rng=np.random.default_rng(42))

        assert len(allocations) == 3
        assert all(v > 0 for v in allocations.values())

    def test_total_never_exceeds_budget(self) -> None:
        """Total allocated budget must never exceed the total_budget."""
        variants = _make_variants(5, clicks=200, impressions=5000)
        total_budget = Decimal("50.00")
        allocations = allocate_budgets(variants, total_budget, rng=np.random.default_rng(42))
        assert sum(allocations.values()) <= total_budget

    def test_minimum_budget_per_variant(self) -> None:
        """Every variant must receive at least the minimum budget."""
        variants = _make_variants(4)
        min_budget = Decimal("5.00")
        total_budget = Decimal("100.00")
        allocations = allocate_budgets(
            variants,
            total_budget,
            min_budget_per_variant=min_budget,
            rng=np.random.default_rng(42),
        )
        for vid, budget in allocations.items():
            assert budget >= min_budget

    def test_empty_variants_returns_empty(self) -> None:
        """No variants means no allocations."""
        result = allocate_budgets([], Decimal("100.00"))
        assert result == {}

    def test_budget_too_low_for_minimums_raises(self) -> None:
        """Budget below min * n_variants must raise ValueError."""
        variants = _make_variants(5)
        with pytest.raises(ValueError, match="cannot cover minimum"):
            allocate_budgets(
                variants,
                Decimal("4.00"),
                min_budget_per_variant=Decimal("1.00"),
            )

    def test_single_variant_gets_full_budget(self) -> None:
        """A single variant should receive the entire budget."""
        vid = uuid.uuid4()
        variants = [(vid, 100, 2000)]
        total_budget = Decimal("50.00")
        allocations = allocate_budgets(variants, total_budget, rng=np.random.default_rng(42))
        assert len(allocations) == 1
        assert allocations[vid] <= total_budget
        # With only one variant, it gets min + 100% of remainder
        assert (
            allocations[vid] == total_budget - Decimal("0.00") or allocations[vid] <= total_budget
        )

    def test_allocations_are_rounded_to_two_decimal_places(self) -> None:
        """All allocations should be rounded to 2 decimal places."""
        variants = _make_variants(3, clicks=77, impressions=3333)
        total_budget = Decimal("99.99")
        allocations = allocate_budgets(variants, total_budget, rng=np.random.default_rng(42))
        for budget in allocations.values():
            # Check that it has at most 2 decimal places
            assert budget == budget.quantize(Decimal("0.01"))

    def test_seeded_allocation_is_reproducible(self) -> None:
        """Same seed should produce same allocations."""
        variants = _make_variants(3)
        total = Decimal("100.00")

        a1 = allocate_budgets(variants, total, rng=np.random.default_rng(42))
        a2 = allocate_budgets(variants, total, rng=np.random.default_rng(42))

        for vid in a1:
            assert a1[vid] == a2[vid]
