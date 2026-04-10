"""Tests for the AnalystAgent with mocked Anthropic client."""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from src.agents.analyst import AnalystAgent, _detect_fatigued_variants
from src.models.analysis import AnalysisResult
from src.models.metrics import DailyRollup
from src.models.variant import VariantResponse, VariantStatus
from tests.factories import build_variant_data


def _make_summary_response(summary_text: str) -> SimpleNamespace:
    """Build a mock Anthropic response with a write_summary tool call."""
    return SimpleNamespace(
        stop_reason="end_turn",
        content=[
            SimpleNamespace(
                type="tool_use",
                name="write_summary",
                input={"summary": summary_text},
            ),
        ],
        usage=SimpleNamespace(input_tokens=200, output_tokens=100),
    )


@pytest.fixture()
def mock_client() -> AsyncMock:
    """Return an AsyncMock of anthropic.AsyncAnthropic."""
    client = AsyncMock()
    client.messages = AsyncMock()
    client.messages.create = AsyncMock()
    return client


@pytest.fixture()
def campaign_id() -> uuid.UUID:
    return uuid.UUID("cccccccc-cccc-cccc-cccc-cccccccccccc")


@pytest.fixture()
def baseline_variant(campaign_id: uuid.UUID) -> VariantResponse:
    return build_variant_data(
        variant_id=uuid.UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"),
        campaign_id=campaign_id,
        variant_code="V1",
        seed=1,
    )


@pytest.fixture()
def test_variant(campaign_id: uuid.UUID) -> VariantResponse:
    return build_variant_data(
        variant_id=uuid.UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"),
        campaign_id=campaign_id,
        variant_code="V2",
        seed=2,
    )


def _make_daily_rollups(
    variant_id: uuid.UUID,
    daily_data: list[tuple[date, int, int, int, Decimal]],
) -> list[DailyRollup]:
    """Create a list of DailyRollup objects from compact data."""
    return [
        DailyRollup(
            day=day,
            variant_id=variant_id,
            impressions=imps,
            clicks=clicks,
            conversions=convs,
            spend=spend,
        )
        for day, imps, clicks, convs, spend in daily_data
    ]


class TestAnalystAgent:
    """Tests for AnalystAgent.analyze_cycle()."""

    async def test_analyze_cycle_returns_analysis_result(
        self,
        mock_client: AsyncMock,
        campaign_id: uuid.UUID,
        baseline_variant: VariantResponse,
        test_variant: VariantResponse,
    ) -> None:
        """analyze_cycle should return a fully populated AnalysisResult."""
        mock_client.messages.create.return_value = _make_summary_response(
            "V2 outperformed the baseline with a 5% CTR vs 2%."
        )

        agent = AnalystAgent(client=mock_client, model="claude-sonnet-4-20250514")

        baseline_rollups = _make_daily_rollups(
            baseline_variant.id,
            [
                (date(2026, 4, 1), 5000, 100, 10, Decimal("50.00")),
                (date(2026, 4, 2), 5000, 100, 10, Decimal("50.00")),
                (date(2026, 4, 3), 5000, 100, 10, Decimal("50.00")),
            ],
        )
        test_rollups = _make_daily_rollups(
            test_variant.id,
            [
                (date(2026, 4, 1), 5000, 250, 25, Decimal("125.00")),
                (date(2026, 4, 2), 5000, 250, 25, Decimal("125.00")),
                (date(2026, 4, 3), 5000, 250, 25, Decimal("125.00")),
            ],
        )

        daily_rollups_by_variant = {
            baseline_variant.id: baseline_rollups,
            test_variant.id: test_rollups,
        }

        result = await agent.analyze_cycle(
            campaign_id=campaign_id,
            cycle_number=1,
            variants=[baseline_variant, test_variant],
            daily_rollups_by_variant=daily_rollups_by_variant,
            baseline_variant_id=baseline_variant.id,
            confidence_threshold=0.95,
            min_impressions=1000,
        )

        assert isinstance(result, AnalysisResult)
        assert result.campaign_id == campaign_id
        assert result.cycle_number == 1
        assert isinstance(result.summary, str)
        assert len(result.summary) > 0

    async def test_winners_are_detected(
        self,
        mock_client: AsyncMock,
        campaign_id: uuid.UUID,
        baseline_variant: VariantResponse,
        test_variant: VariantResponse,
    ) -> None:
        """A variant with significantly higher CTR should be marked as winner."""
        mock_client.messages.create.return_value = _make_summary_response("V2 is a winner.")

        agent = AnalystAgent(client=mock_client, model="claude-sonnet-4-20250514")

        # Baseline: 2% CTR, Test: 5% CTR with large sample
        baseline_rollups = _make_daily_rollups(
            baseline_variant.id,
            [(date(2026, 4, 1), 10000, 200, 20, Decimal("100.00"))],
        )
        test_rollups = _make_daily_rollups(
            test_variant.id,
            [(date(2026, 4, 1), 10000, 500, 50, Decimal("250.00"))],
        )

        result = await agent.analyze_cycle(
            campaign_id=campaign_id,
            cycle_number=1,
            variants=[baseline_variant, test_variant],
            daily_rollups_by_variant={
                baseline_variant.id: baseline_rollups,
                test_variant.id: test_rollups,
            },
            baseline_variant_id=baseline_variant.id,
        )

        # V2 should be in variant_results with a winner recommendation
        winners = [
            vr for vr in result.variant_results if vr.recommended_action == VariantStatus.WINNER
        ]
        assert len(winners) == 1
        assert winners[0].variant_code == "V2"

    async def test_losers_are_detected(
        self,
        mock_client: AsyncMock,
        campaign_id: uuid.UUID,
        baseline_variant: VariantResponse,
        test_variant: VariantResponse,
    ) -> None:
        """A variant with significantly lower CTR should be marked as paused."""
        mock_client.messages.create.return_value = _make_summary_response("V2 underperformed.")

        agent = AnalystAgent(client=mock_client, model="claude-sonnet-4-20250514")

        # Baseline: 5% CTR, Test: 1% CTR
        baseline_rollups = _make_daily_rollups(
            baseline_variant.id,
            [(date(2026, 4, 1), 10000, 500, 50, Decimal("250.00"))],
        )
        test_rollups = _make_daily_rollups(
            test_variant.id,
            [(date(2026, 4, 1), 10000, 100, 10, Decimal("50.00"))],
        )

        result = await agent.analyze_cycle(
            campaign_id=campaign_id,
            cycle_number=1,
            variants=[baseline_variant, test_variant],
            daily_rollups_by_variant={
                baseline_variant.id: baseline_rollups,
                test_variant.id: test_rollups,
            },
            baseline_variant_id=baseline_variant.id,
        )

        losers = [
            vr for vr in result.variant_results if vr.recommended_action == VariantStatus.PAUSED
        ]
        assert len(losers) == 1
        assert losers[0].variant_code == "V2"

    async def test_element_insights_are_computed(
        self,
        mock_client: AsyncMock,
        campaign_id: uuid.UUID,
        baseline_variant: VariantResponse,
        test_variant: VariantResponse,
    ) -> None:
        """Element insights should be populated in the result."""
        mock_client.messages.create.return_value = _make_summary_response("Analysis complete.")

        agent = AnalystAgent(client=mock_client, model="claude-sonnet-4-20250514")

        baseline_rollups = _make_daily_rollups(
            baseline_variant.id,
            [(date(2026, 4, 1), 5000, 150, 15, Decimal("75.00"))],
        )
        test_rollups = _make_daily_rollups(
            test_variant.id,
            [(date(2026, 4, 1), 5000, 200, 20, Decimal("100.00"))],
        )

        result = await agent.analyze_cycle(
            campaign_id=campaign_id,
            cycle_number=1,
            variants=[baseline_variant, test_variant],
            daily_rollups_by_variant={
                baseline_variant.id: baseline_rollups,
                test_variant.id: test_rollups,
            },
        )

        assert len(result.element_insights) > 0
        # Each insight should have a slot name and value
        for ei in result.element_insights:
            assert ei.slot_name
            assert ei.slot_value
            assert ei.variants_tested >= 1


class TestDetectFatiguedVariants:
    """Tests for the _detect_fatigued_variants helper."""

    def test_fatigued_variant_detected(self) -> None:
        """A variant with 3+ declining days should appear in the fatigued list."""
        vid = uuid.uuid4()
        rollups = [
            DailyRollup(
                day=date(2026, 4, d),
                variant_id=vid,
                impressions=5000,
                clicks=clicks,
                conversions=10,
                spend=Decimal("50.00"),
            )
            for d, clicks in [(1, 250), (2, 200), (3, 150), (4, 100)]
        ]
        result = _detect_fatigued_variants({vid: rollups})
        assert vid in result

    def test_healthy_variant_not_detected(self) -> None:
        """A variant with increasing CTR should not be flagged."""
        vid = uuid.uuid4()
        rollups = [
            DailyRollup(
                day=date(2026, 4, d),
                variant_id=vid,
                impressions=5000,
                clicks=clicks,
                conversions=10,
                spend=Decimal("50.00"),
            )
            for d, clicks in [(1, 100), (2, 150), (3, 200), (4, 250)]
        ]
        result = _detect_fatigued_variants({vid: rollups})
        assert vid not in result
