"""Pairwise element interaction tracker.

Computes lift effects for every pair of creative elements, revealing
synergy (positive lift) or conflict (negative lift) between elements.

Canonical ordering is enforced: slot_a_name < slot_b_name, or when
slots are equal, slot_a_value < slot_b_value. This prevents duplicate
pairs and matches the DB CHECK constraint.
"""

from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations


@dataclass(frozen=True)
class InteractionResult:
    """Performance result for a pair of creative elements.

    Attributes:
        slot_a_name: First slot name (canonical ordering: a < b).
        slot_a_value: Value for slot A.
        slot_b_name: Second slot name (canonical ordering: a < b).
        slot_b_value: Value for slot B.
        combined_avg_ctr: Average CTR of variants containing BOTH elements.
        solo_a_avg_ctr: Average CTR of element A in variants WITHOUT element B.
        solo_b_avg_ctr: Average CTR of element B in variants WITHOUT element A.
        lift: Interaction lift = combined_avg / max(solo_a_avg, solo_b_avg) - 1.
            Positive means synergy, negative means conflict.
        variants_combined: Number of variants that had both elements.
    """

    slot_a_name: str
    slot_a_value: str
    slot_b_name: str
    slot_b_value: str
    combined_avg_ctr: float
    solo_a_avg_ctr: float
    solo_b_avg_ctr: float
    lift: float
    variants_combined: int


def _canonicalize_pair(
    slot_a_name: str,
    slot_a_value: str,
    slot_b_name: str,
    slot_b_value: str,
) -> tuple[str, str, str, str]:
    """Return the pair in canonical order matching the DB CHECK constraint.

    Rule: slot_a_name < slot_b_name, or if slots are the same,
    slot_a_value < slot_b_value.
    """
    if slot_a_name > slot_b_name:
        return slot_b_name, slot_b_value, slot_a_name, slot_a_value
    if slot_a_name == slot_b_name and slot_a_value > slot_b_value:
        return slot_a_name, slot_b_value, slot_b_name, slot_a_value
    return slot_a_name, slot_a_value, slot_b_name, slot_b_value


def compute_interactions(
    variants_with_metrics: list[tuple[dict[str, str], float]],
    min_combined_variants: int = 2,
) -> list[InteractionResult]:
    """Compute pairwise interaction effects across all element pairs.

    For each unique pair of (slot_name, slot_value) present in the data,
    calculates:
    - Combined average CTR (variants containing both elements)
    - Solo average CTR for each element (variants with A but not B, and vice versa)
    - Lift = combined_avg / max(solo_a_avg, solo_b_avg) - 1

    Args:
        variants_with_metrics: List of (genome_dict, avg_ctr) tuples.
            Each genome_dict maps slot_name to slot_value.
        min_combined_variants: Minimum number of variants containing both
            elements to include the pair in results. Default 2.

    Returns:
        List of InteractionResult sorted by absolute lift descending.
    """
    if not variants_with_metrics:
        return []

    # Build index: (slot_name, slot_value) -> list of (variant_index, ctr)
    element_variants: dict[tuple[str, str], list[tuple[int, float]]] = {}

    for idx, (genome, ctr) in enumerate(variants_with_metrics):
        for slot_name, slot_value in genome.items():
            key = (slot_name, slot_value)
            if key not in element_variants:
                element_variants[key] = []
            element_variants[key].append((idx, ctr))

    # For quick set membership checks: element -> set of variant indices
    element_variant_indices: dict[tuple[str, str], set[int]] = {
        key: {idx for idx, _ in entries} for key, entries in element_variants.items()
    }

    # For quick CTR lookup by variant index
    variant_ctrs: dict[int, float] = {
        idx: ctr for idx, (_, ctr) in enumerate(variants_with_metrics)
    }

    results: list[InteractionResult] = []
    all_elements = list(element_variants.keys())

    for elem_a, elem_b in combinations(all_elements, 2):
        slot_a_name, slot_a_value = elem_a
        slot_b_name, slot_b_value = elem_b

        # Skip pairs within the same slot that have the same value
        if slot_a_name == slot_b_name and slot_a_value == slot_b_value:
            continue

        indices_a = element_variant_indices[elem_a]
        indices_b = element_variant_indices[elem_b]

        combined_indices = indices_a & indices_b
        solo_a_indices = indices_a - indices_b
        solo_b_indices = indices_b - indices_a

        if len(combined_indices) < min_combined_variants:
            continue

        # Need solo data for both elements to compute meaningful lift
        if not solo_a_indices or not solo_b_indices:
            continue

        combined_avg_ctr = sum(variant_ctrs[i] for i in combined_indices) / len(combined_indices)
        solo_a_avg_ctr = sum(variant_ctrs[i] for i in solo_a_indices) / len(solo_a_indices)
        solo_b_avg_ctr = sum(variant_ctrs[i] for i in solo_b_indices) / len(solo_b_indices)

        best_solo = max(solo_a_avg_ctr, solo_b_avg_ctr)
        if best_solo == 0.0:
            # Cannot compute meaningful lift when baseline is zero
            continue

        lift = combined_avg_ctr / best_solo - 1

        # Canonicalize pair ordering
        cn_a_name, cn_a_value, cn_b_name, cn_b_value = _canonicalize_pair(
            slot_a_name, slot_a_value, slot_b_name, slot_b_value
        )

        results.append(
            InteractionResult(
                slot_a_name=cn_a_name,
                slot_a_value=cn_a_value,
                slot_b_name=cn_b_name,
                slot_b_value=cn_b_value,
                combined_avg_ctr=combined_avg_ctr,
                solo_a_avg_ctr=solo_a_avg_ctr,
                solo_b_avg_ctr=solo_b_avg_ctr,
                lift=lift,
                variants_combined=len(combined_indices),
            )
        )

    # Sort by absolute lift descending (strongest interactions first)
    results.sort(key=lambda r: abs(r.lift), reverse=True)
    return results
