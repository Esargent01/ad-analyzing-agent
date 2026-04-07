"""Audience fatigue detection for ad variants.

Detects when a variant's CTR has been declining over consecutive days,
signaling audience fatigue and the need to pause or refresh the creative.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass


@dataclass(frozen=True)
class FatigueResult:
    """Result of a fatigue detection check.

    Attributes:
        is_fatigued: True if CTR has declined for ``window`` or more
            consecutive days.
        consecutive_decline_days: Number of consecutive days with
            declining CTR (from the most recent day backward).
        trend_slope: Average daily CTR change over the decline period.
            Negative means declining. 0.0 if no decline detected.
    """

    is_fatigued: bool
    consecutive_decline_days: int
    trend_slope: float


def detect_fatigue(
    daily_ctrs: list[tuple[datetime.date, float]],
    window: int = 3,
) -> FatigueResult:
    """Detect audience fatigue from daily CTR data.

    A variant is considered fatigued when its CTR has declined for
    ``window`` or more consecutive days (most recent days).

    Args:
        daily_ctrs: List of (date, ctr) tuples. Need not be sorted;
            the function sorts internally by date ascending.
        window: Minimum consecutive declining days to flag fatigue.
            Default 3 per the CLAUDE.md spec.

    Returns:
        FatigueResult with fatigue status, decline count, and slope.
    """
    if len(daily_ctrs) < 2:
        return FatigueResult(is_fatigued=False, consecutive_decline_days=0, trend_slope=0.0)

    # Sort by date ascending
    sorted_ctrs = sorted(daily_ctrs, key=lambda pair: pair[0])

    # Count consecutive declines from the most recent day backward
    consecutive_declines = 0
    for i in range(len(sorted_ctrs) - 1, 0, -1):
        current_ctr = sorted_ctrs[i][1]
        previous_ctr = sorted_ctrs[i - 1][1]
        if current_ctr < previous_ctr:
            consecutive_declines += 1
        else:
            break

    is_fatigued = consecutive_declines >= window

    # Compute slope over the decline period
    trend_slope = 0.0
    if consecutive_declines > 0:
        # Decline covers consecutive_declines + 1 data points
        decline_start_idx = len(sorted_ctrs) - 1 - consecutive_declines
        start_ctr = sorted_ctrs[decline_start_idx][1]
        end_ctr = sorted_ctrs[-1][1]
        trend_slope = (end_ctr - start_ctr) / consecutive_declines

    return FatigueResult(
        is_fatigued=is_fatigued,
        consecutive_decline_days=consecutive_declines,
        trend_slope=trend_slope,
    )
