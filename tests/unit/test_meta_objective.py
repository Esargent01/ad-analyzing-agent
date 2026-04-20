"""Tests for the Meta objective normaliser.

Locks in the legacy → ODAX mapping. If Meta introduces a new objective
or renames an existing one, the suite must update in lockstep with
``src/adapters/meta_objective.py`` — otherwise unknown values will
silently collapse to ``OUTCOME_UNKNOWN`` and downstream dashboards
will show Sales-flavoured output for campaigns that aren't Sales.
"""

from __future__ import annotations

import pytest

from src.adapters.meta_objective import (
    ODAX_VALUES,
    UNKNOWN_OBJECTIVE,
    display_label,
    normalize_meta_objective,
)


class TestODAXPassthrough:
    @pytest.mark.parametrize("value", sorted(ODAX_VALUES))
    def test_canonical_odax_values_pass_through(self, value: str) -> None:
        assert normalize_meta_objective(value) == value


class TestLegacyMapping:
    # Every legacy string we're aware of + its expected canonical ODAX
    # target. The reverse parametrize both exercises the map and serves
    # as documentation for reviewers.
    @pytest.mark.parametrize(
        ("legacy", "expected"),
        [
            # Sales
            ("CONVERSIONS", "OUTCOME_SALES"),
            ("CATALOG_SALES", "OUTCOME_SALES"),
            ("PRODUCT_CATALOG_SALES", "OUTCOME_SALES"),
            # Leads
            ("LEAD_GENERATION", "OUTCOME_LEADS"),
            ("MESSAGES", "OUTCOME_LEADS"),
            # Engagement
            ("POST_ENGAGEMENT", "OUTCOME_ENGAGEMENT"),
            ("PAGE_LIKES", "OUTCOME_ENGAGEMENT"),
            ("EVENT_RESPONSES", "OUTCOME_ENGAGEMENT"),
            ("VIDEO_VIEWS", "OUTCOME_ENGAGEMENT"),
            # Traffic
            ("LINK_CLICKS", "OUTCOME_TRAFFIC"),
            # Awareness
            ("BRAND_AWARENESS", "OUTCOME_AWARENESS"),
            ("REACH", "OUTCOME_AWARENESS"),
            ("IMPRESSIONS", "OUTCOME_AWARENESS"),
            # App Promotion
            ("APP_INSTALLS", "OUTCOME_APP_PROMOTION"),
        ],
    )
    def test_legacy_values_map_to_odax(self, legacy: str, expected: str) -> None:
        assert normalize_meta_objective(legacy) == expected


class TestUnknownFallback:
    @pytest.mark.parametrize(
        "value",
        [
            None,
            "",
            "UNKNOWN",
            "OUTCOME_SOMETHING_NEW",
            "not_a_real_objective",
            "POST_LIKES",  # close to POST_ENGAGEMENT but not in the map
        ],
    )
    def test_unmapped_values_fall_back_to_sentinel(self, value: str | None) -> None:
        assert normalize_meta_objective(value) == UNKNOWN_OBJECTIVE


class TestDisplayLabel:
    @pytest.mark.parametrize(
        ("objective", "label"),
        [
            ("OUTCOME_SALES", "Sales"),
            ("OUTCOME_LEADS", "Leads"),
            ("OUTCOME_ENGAGEMENT", "Engagement"),
            ("OUTCOME_TRAFFIC", "Traffic"),
            ("OUTCOME_AWARENESS", "Awareness"),
            ("OUTCOME_APP_PROMOTION", "App promotion"),
            (UNKNOWN_OBJECTIVE, "Unknown"),
        ],
    )
    def test_display_label_for_every_canonical_value(
        self, objective: str, label: str
    ) -> None:
        assert display_label(objective) == label

    def test_display_label_unmapped_falls_back_to_unknown(self) -> None:
        assert display_label("NOT_A_REAL_OBJECTIVE") == "Unknown"
