"""Tests for audience fatigue detection."""

from __future__ import annotations

import datetime

from src.services.fatigue import detect_fatigue


class TestDetectFatigue:
    """Tests for the detect_fatigue() function."""

    def test_three_consecutive_declining_days_is_fatigued(self) -> None:
        """3+ consecutive declining days should flag fatigue (default window=3)."""
        daily_ctrs = [
            (datetime.date(2026, 4, 1), 0.05),
            (datetime.date(2026, 4, 2), 0.04),
            (datetime.date(2026, 4, 3), 0.03),
            (datetime.date(2026, 4, 4), 0.02),
        ]
        result = detect_fatigue(daily_ctrs)
        assert result.is_fatigued is True
        assert result.consecutive_decline_days == 3
        assert result.trend_slope < 0

    def test_two_declining_days_not_fatigued(self) -> None:
        """2 declining days should NOT be flagged with default window=3."""
        daily_ctrs = [
            (datetime.date(2026, 4, 1), 0.05),
            (datetime.date(2026, 4, 2), 0.04),
            (datetime.date(2026, 4, 3), 0.03),
        ]
        result = detect_fatigue(daily_ctrs)
        assert result.is_fatigued is False
        assert result.consecutive_decline_days == 2

    def test_increasing_ctr_not_fatigued(self) -> None:
        """Increasing CTR should never be flagged as fatigued."""
        daily_ctrs = [
            (datetime.date(2026, 4, 1), 0.02),
            (datetime.date(2026, 4, 2), 0.03),
            (datetime.date(2026, 4, 3), 0.04),
            (datetime.date(2026, 4, 4), 0.05),
        ]
        result = detect_fatigue(daily_ctrs)
        assert result.is_fatigued is False
        assert result.consecutive_decline_days == 0
        assert result.trend_slope == 0.0

    def test_single_data_point_not_fatigued(self) -> None:
        """Fewer than 2 data points should return not fatigued."""
        daily_ctrs = [
            (datetime.date(2026, 4, 1), 0.05),
        ]
        result = detect_fatigue(daily_ctrs)
        assert result.is_fatigued is False
        assert result.consecutive_decline_days == 0
        assert result.trend_slope == 0.0

    def test_empty_input_not_fatigued(self) -> None:
        """Empty data returns not fatigued."""
        result = detect_fatigue([])
        assert result.is_fatigued is False
        assert result.consecutive_decline_days == 0

    def test_unsorted_input_is_handled(self) -> None:
        """Input not sorted by date should still detect fatigue correctly."""
        # Deliberately unsorted -- should be sorted internally
        daily_ctrs = [
            (datetime.date(2026, 4, 4), 0.01),
            (datetime.date(2026, 4, 1), 0.05),
            (datetime.date(2026, 4, 3), 0.03),
            (datetime.date(2026, 4, 2), 0.04),
        ]
        result = detect_fatigue(daily_ctrs)
        assert result.is_fatigued is True
        assert result.consecutive_decline_days == 3

    def test_custom_window(self) -> None:
        """Custom window should change the fatigue threshold."""
        daily_ctrs = [
            (datetime.date(2026, 4, 1), 0.05),
            (datetime.date(2026, 4, 2), 0.04),
            (datetime.date(2026, 4, 3), 0.03),
        ]
        # window=2: 2 declining days should trigger
        result = detect_fatigue(daily_ctrs, window=2)
        assert result.is_fatigued is True
        assert result.consecutive_decline_days == 2

    def test_decline_then_increase_counts_recent_only(self) -> None:
        """Only the most recent consecutive decline counts.

        Pattern: decline, decline, INCREASE, decline -- only 1 recent decline.
        """
        daily_ctrs = [
            (datetime.date(2026, 4, 1), 0.05),
            (datetime.date(2026, 4, 2), 0.04),
            (datetime.date(2026, 4, 3), 0.03),
            (datetime.date(2026, 4, 4), 0.04),  # increase breaks the streak
            (datetime.date(2026, 4, 5), 0.035),
        ]
        result = detect_fatigue(daily_ctrs)
        assert result.is_fatigued is False
        assert result.consecutive_decline_days == 1

    def test_trend_slope_is_negative(self) -> None:
        """The slope should reflect the average daily CTR change."""
        daily_ctrs = [
            (datetime.date(2026, 4, 1), 0.06),
            (datetime.date(2026, 4, 2), 0.05),
            (datetime.date(2026, 4, 3), 0.04),
            (datetime.date(2026, 4, 4), 0.03),
        ]
        result = detect_fatigue(daily_ctrs)
        # 3 declines. slope = (0.03 - 0.06) / 3 = -0.01
        assert abs(result.trend_slope - (-0.01)) < 1e-10

    def test_flat_ctr_not_fatigued(self) -> None:
        """Flat CTR (no decline) should not be flagged."""
        daily_ctrs = [
            (datetime.date(2026, 4, 1), 0.03),
            (datetime.date(2026, 4, 2), 0.03),
            (datetime.date(2026, 4, 3), 0.03),
            (datetime.date(2026, 4, 4), 0.03),
        ]
        result = detect_fatigue(daily_ctrs)
        assert result.is_fatigued is False
        assert result.consecutive_decline_days == 0
