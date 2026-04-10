"""Thompson sampling budget allocation for ad variants.

Uses Beta(successes+1, failures+1) prior per variant to balance
exploration and exploitation when distributing budget across
active variants.
"""

from __future__ import annotations

import uuid
from decimal import ROUND_HALF_UP, Decimal

import numpy as np
from numpy.random import Generator as NumpyGenerator


class ThompsonSampler:
    """Allocates budget across variants using Thompson sampling.

    Each variant is modelled with a Beta distribution parameterized by
    its observed clicks (successes) and non-click impressions (failures).
    Budget is allocated proportionally to samples drawn from each
    variant's posterior distribution.

    Args:
        rng: A numpy random Generator for reproducible sampling.
             If None, a new default Generator is created.
    """

    def __init__(self, rng: NumpyGenerator | None = None) -> None:
        self._rng: NumpyGenerator = rng or np.random.default_rng()

    def sample_weights(
        self,
        variants: list[tuple[uuid.UUID, int, int]],
    ) -> dict[uuid.UUID, float]:
        """Draw from each variant's Beta posterior and return normalized weights.

        Args:
            variants: List of (variant_id, clicks, impressions) tuples.

        Returns:
            Dict mapping variant_id to a weight in [0, 1] that sums to 1.0.
        """
        samples: dict[uuid.UUID, float] = {}
        for variant_id, clicks, impressions in variants:
            alpha = clicks + 1
            beta = (impressions - clicks) + 1
            samples[variant_id] = float(self._rng.beta(alpha, beta))

        total = sum(samples.values())
        if total == 0:
            # Uniform fallback if all samples are zero (shouldn't happen with Beta)
            n = len(variants)
            return {vid: 1.0 / n for vid, _, _ in variants}

        return {vid: sample / total for vid, sample in samples.items()}


def allocate_budgets(
    variants: list[tuple[uuid.UUID, int, int]],
    total_budget: Decimal,
    min_budget_per_variant: Decimal = Decimal("1.00"),
    rng: NumpyGenerator | None = None,
) -> dict[uuid.UUID, Decimal]:
    """Allocate budget across variants using Thompson sampling.

    Args:
        variants: List of (variant_id, clicks, impressions) tuples.
        total_budget: Total daily budget to distribute.
        min_budget_per_variant: Floor budget for every variant to ensure
            each gets at least some spend. Default $1.00.
        rng: Optional numpy Generator for reproducible tests.

    Returns:
        Dict mapping each variant_id to its allocated Decimal budget.
        Allocations are rounded to 2 decimal places and guaranteed to
        sum to at most ``total_budget``.

    Raises:
        ValueError: If total_budget cannot cover the minimum for all variants.
    """
    if not variants:
        return {}

    n_variants = len(variants)
    min_total = min_budget_per_variant * n_variants

    if total_budget < min_total:
        raise ValueError(
            f"Total budget {total_budget} cannot cover minimum "
            f"{min_budget_per_variant} x {n_variants} variants = {min_total}"
        )

    sampler = ThompsonSampler(rng=rng)
    weights = sampler.sample_weights(variants)

    # Reserve minimums, then distribute the remainder proportionally
    remainder = total_budget - min_total
    allocations: dict[uuid.UUID, Decimal] = {}

    for variant_id, _, _ in variants:
        proportional = Decimal(str(weights[variant_id])) * remainder
        budget = min_budget_per_variant + proportional
        allocations[variant_id] = budget.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    # Adjust for rounding so we never exceed total_budget
    allocated_sum = sum(allocations.values())
    if allocated_sum > total_budget:
        # Trim the largest allocation to compensate
        largest_id = max(allocations, key=lambda vid: allocations[vid])
        overshoot = allocated_sum - total_budget
        allocations[largest_id] -= overshoot

    return allocations
