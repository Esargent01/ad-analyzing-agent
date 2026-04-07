"""Statistical significance tests for ad creative comparison.

All functions are pure (no async, no side effects). Statistical
calculations use scipy.stats exclusively -- never LLM.
"""

from __future__ import annotations

import math

from scipy import stats


def compare_variants(
    baseline_clicks: int,
    baseline_impressions: int,
    variant_clicks: int,
    variant_impressions: int,
    confidence_threshold: float = 0.95,
) -> tuple[float, float, bool]:
    """Two-proportion z-test comparing variant CTR against baseline.

    Uses the pooled proportion for the standard error, following the
    standard two-proportion z-test methodology.

    Args:
        baseline_clicks: Number of clicks for the baseline variant.
        baseline_impressions: Number of impressions for the baseline variant.
        variant_clicks: Number of clicks for the test variant.
        variant_impressions: Number of impressions for the test variant.
        confidence_threshold: Significance level expressed as confidence
            (e.g. 0.95 means alpha = 0.05). Default 0.95.

    Returns:
        Tuple of (z_score, p_value, is_significant).
        ``is_significant`` is True when p_value < (1 - confidence_threshold).
    """
    if baseline_impressions == 0 or variant_impressions == 0:
        return 0.0, 1.0, False

    p_baseline = baseline_clicks / baseline_impressions
    p_variant = variant_clicks / variant_impressions

    # Pooled proportion
    total_clicks = baseline_clicks + variant_clicks
    total_impressions = baseline_impressions + variant_impressions
    p_pooled = total_clicks / total_impressions

    # Standard error of the difference
    se = math.sqrt(
        p_pooled * (1 - p_pooled) * (1 / baseline_impressions + 1 / variant_impressions)
    )

    if se == 0.0:
        return 0.0, 1.0, False

    z_score = (p_variant - p_baseline) / se
    # Two-tailed p-value
    p_value: float = 2 * (1 - stats.norm.cdf(abs(z_score)))

    alpha = 1 - confidence_threshold
    is_significant = bool(p_value < alpha)

    return z_score, p_value, is_significant


def element_significance(
    element_ctrs: list[float],
    global_mean_ctr: float,
) -> tuple[float, float, float]:
    """One-sample t-test of element CTRs against the global mean.

    Answers: "Is the average CTR of variants using this element
    significantly different from the overall campaign average?"

    Args:
        element_ctrs: List of CTR values from variants containing this element.
        global_mean_ctr: The campaign-wide average CTR.

    Returns:
        Tuple of (t_statistic, p_value, confidence).
        ``confidence`` is ``1 - p_value`` expressed as a percentage (0-100).
        Returns (0.0, 1.0, 0.0) when there are fewer than 2 observations.
    """
    if len(element_ctrs) < 2:
        return 0.0, 1.0, 0.0

    result = stats.ttest_1samp(element_ctrs, global_mean_ctr)
    t_stat: float = float(result.statistic)
    p_value: float = float(result.pvalue)

    # Handle NaN from identical observations
    if math.isnan(t_stat):
        t_stat = 0.0
    if math.isnan(p_value):
        p_value = 1.0

    confidence = (1 - p_value) * 100
    return t_stat, p_value, confidence


def has_sufficient_data(impressions: int, min_required: int = 1000) -> bool:
    """Check whether a variant has enough impressions for significance testing.

    Args:
        impressions: Total impressions the variant has received.
        min_required: Minimum impressions needed. Default 1000 per CLAUDE.md.

    Returns:
        True if impressions >= min_required.
    """
    return impressions >= min_required
