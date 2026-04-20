"""Unit tests for ``MetaAdapter._parse_insights_to_metrics``.

The Meta adapter scrapes the ``actions`` array on each Insights row for
named action types (``lead``, ``post_engagement``, ``offsite_conversion.fb_pixel_purchase``,
etc.) and turns them into fields on :class:`AdMetrics`. These tests lock
in the three objective-specific fields (``leads``, ``post_engagements``,
``conversions``) since they drive non-Sales reporting; if Meta's API
renames or splits the action types the parser relies on, these tests
fail first.

The parser is a static method with no external dependencies, so we
call it directly — no adapter instance, no Meta SDK mocking needed.
"""

from __future__ import annotations

from src.adapters.meta import MetaAdapter


def _insight(**overrides: object) -> dict[str, object]:
    """Minimal Insights-row shape. Callers override just the ``actions``
    list + any scalar fields they want to exercise."""
    base: dict[str, object] = {
        "impressions": 1000,
        "reach": 800,
        "clicks": 20,
        "spend": 10.0,
        "actions": [],
        "action_values": [],
    }
    base.update(overrides)
    return base


class TestLeadsParsing:
    """OUTCOME_LEADS campaigns — ``leads`` field populates from three action types."""

    def test_onsite_lead_grouped(self) -> None:
        raw = _insight(
            actions=[{"action_type": "onsite_conversion.lead_grouped", "value": "4"}]
        )
        m = MetaAdapter._parse_insights_to_metrics(raw)
        assert m.leads == 4

    def test_offsite_pixel_lead(self) -> None:
        raw = _insight(
            actions=[{"action_type": "offsite_conversion.fb_pixel_lead", "value": "7"}]
        )
        m = MetaAdapter._parse_insights_to_metrics(raw)
        assert m.leads == 7

    def test_plain_lead(self) -> None:
        raw = _insight(actions=[{"action_type": "lead", "value": "3"}])
        m = MetaAdapter._parse_insights_to_metrics(raw)
        assert m.leads == 3

    def test_all_lead_sources_sum(self) -> None:
        raw = _insight(
            actions=[
                {"action_type": "lead", "value": "2"},
                {"action_type": "onsite_conversion.lead_grouped", "value": "3"},
                {"action_type": "offsite_conversion.fb_pixel_lead", "value": "1"},
            ]
        )
        m = MetaAdapter._parse_insights_to_metrics(raw)
        assert m.leads == 6

    def test_leads_flow_into_conversions(self) -> None:
        """Legacy CTR/CPA aggregates still need to see lead campaigns
        as converting — leads are additive to ``conversions``."""
        raw = _insight(actions=[{"action_type": "lead", "value": "5"}])
        m = MetaAdapter._parse_insights_to_metrics(raw)
        assert m.conversions == 5


class TestPostEngagementsParsing:
    """OUTCOME_ENGAGEMENT campaigns — prefer the aggregate
    ``post_engagement`` action but fall back to summing individuals."""

    def test_aggregate_post_engagement(self) -> None:
        raw = _insight(
            actions=[{"action_type": "post_engagement", "value": "42"}]
        )
        m = MetaAdapter._parse_insights_to_metrics(raw)
        assert m.post_engagements == 42

    def test_individual_actions_sum_when_no_aggregate(self) -> None:
        raw = _insight(
            actions=[
                {"action_type": "post_reaction", "value": "10"},
                {"action_type": "comment", "value": "3"},
                {"action_type": "like", "value": "25"},
                {"action_type": "post", "value": "2"},
            ]
        )
        m = MetaAdapter._parse_insights_to_metrics(raw)
        assert m.post_engagements == 40

    def test_aggregate_wins_over_individuals(self) -> None:
        """If Meta reports both the rollup and the breakdowns, the
        rollup is authoritative — we don't double-count."""
        raw = _insight(
            actions=[
                {"action_type": "post_engagement", "value": "100"},
                {"action_type": "post_reaction", "value": "25"},
                {"action_type": "comment", "value": "5"},
            ]
        )
        m = MetaAdapter._parse_insights_to_metrics(raw)
        assert m.post_engagements == 100


class TestEmptyInsights:
    """An empty Insights row (no impressions, no actions) must return
    a valid AdMetrics with all counts at zero — guards against the
    cold-start / no-delivery case."""

    def test_empty_row_returns_zeros(self) -> None:
        m = MetaAdapter._parse_insights_to_metrics({})
        assert m.impressions == 0
        assert m.clicks == 0
        assert m.conversions == 0
        assert m.leads == 0
        assert m.post_engagements == 0
        assert m.spend == 0.0


class TestMixedObjectiveActions:
    """Sales + Leads + Engagement actions on the same row — each field
    isolates to its own action types; no cross-contamination."""

    def test_purchases_leads_engagements_coexist(self) -> None:
        raw = _insight(
            actions=[
                {"action_type": "offsite_conversion.fb_pixel_purchase", "value": "2"},
                {"action_type": "lead", "value": "5"},
                {"action_type": "post_engagement", "value": "33"},
                {"action_type": "link_click", "value": "40"},
            ],
            action_values=[
                {"action_type": "offsite_conversion.fb_pixel_purchase", "value": "199.98"},
            ],
        )
        m = MetaAdapter._parse_insights_to_metrics(raw)
        assert m.purchases == 2
        assert m.leads == 5
        assert m.post_engagements == 33
        assert m.link_clicks == 40
        assert m.purchase_value == 199.98
        # conversions = purchases (2) + leads (5) = 7
        assert m.conversions == 7
