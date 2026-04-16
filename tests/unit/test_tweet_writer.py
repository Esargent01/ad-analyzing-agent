"""Tests for the LLM-powered daily tweet drafter with mocked Anthropic client."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from src.agents.tweet_writer import (
    SKIP_SENTINEL,
    TweetDraft,
    _serialize_report_for_prompt,
    draft_daily_tweet,
)
from src.exceptions import LLMError
from src.models.reports import DailyReport, ReportCycleAction, VariantReport


def _make_tool_use_block(text: str) -> SimpleNamespace:
    return SimpleNamespace(type="tool_use", name="publish_tweet", input={"text": text})


def _make_response(*blocks: SimpleNamespace) -> SimpleNamespace:
    return SimpleNamespace(
        stop_reason="tool_use",
        content=list(blocks),
        usage=SimpleNamespace(input_tokens=100, output_tokens=50),
    )


def _minimal_report(
    *,
    best_variant: VariantReport | None = None,
    actions: list[ReportCycleAction] | None = None,
    total_purchases: int = 12,
) -> DailyReport:
    return DailyReport(
        campaign_name="Kleiber Showcase",
        campaign_id=uuid4(),
        cycle_number=7,
        report_date=date(2026, 4, 15),
        day_number=21,
        total_spend=Decimal("100.00"),
        total_purchases=total_purchases,
        avg_cost_per_purchase=8.33,
        avg_roas=3.1,
        avg_hook_rate_pct=22.0,
        prev_avg_cpa=10.0,
        variants=[],
        best_variant=best_variant,
        actions=actions or [],
    )


def _best_variant() -> VariantReport:
    return VariantReport(
        variant_id=uuid4(),
        variant_code="V7",
        genome={"headline": "40% off", "cta_text": "Shop now"},
        genome_summary="urgency headline + direct CTA",
        hypothesis="Direct CTAs outperform soft asks on this audience",
        status="winner",
        days_active=4,
        spend=Decimal("40.00"),
        purchases=8,
        purchase_value=Decimal("200.00"),
        cost_per_purchase=5.00,
        roas=5.0,
        impressions=3000,
        reach=2500,
        video_views_3s=600,
        video_views_15s=200,
        link_clicks=90,
        landing_page_views=70,
        add_to_carts=20,
        hook_rate_pct=20.0,
        hold_rate_pct=33.0,
        ctr_pct=3.0,
        atc_rate_pct=22.0,
        checkout_rate_pct=40.0,
        frequency=1.2,
    )


@pytest.fixture()
def mock_client() -> AsyncMock:
    client = AsyncMock()
    client.messages = AsyncMock()
    client.messages.create = AsyncMock()
    return client


class TestDraftDailyTweet:
    async def test_returns_validated_draft_on_happy_path(self, mock_client: AsyncMock) -> None:
        body = (
            "Paused 1 laggard, scaled the winner 4x. CPA fell 17% overnight on the "
            "urgency headline. The agent never sleeps."
        )
        mock_client.messages.create.return_value = _make_response(_make_tool_use_block(body))

        report = _minimal_report(
            best_variant=_best_variant(),
            actions=[
                ReportCycleAction(action_type="pause", variant_code="V3", details=None),
                ReportCycleAction(action_type="scale", variant_code="V7", details="4x"),
            ],
        )

        draft = await draft_daily_tweet(
            report=report, client=mock_client, model="claude-sonnet-4-20250514"
        )

        assert isinstance(draft, TweetDraft)
        assert draft.text == body
        assert len(draft.text) <= 280

    async def test_honours_skip_sentinel(self, mock_client: AsyncMock) -> None:
        mock_client.messages.create.return_value = _make_response(
            _make_tool_use_block(SKIP_SENTINEL)
        )

        report = _minimal_report(best_variant=None, actions=[], total_purchases=0)
        draft = await draft_daily_tweet(
            report=report, client=mock_client, model="claude-sonnet-4-20250514"
        )
        assert draft.text == SKIP_SENTINEL

    async def test_raises_when_output_exceeds_280_chars(self, mock_client: AsyncMock) -> None:
        too_long = "x" * 281
        mock_client.messages.create.return_value = _make_response(_make_tool_use_block(too_long))
        report = _minimal_report(best_variant=_best_variant())

        with pytest.raises(LLMError):
            await draft_daily_tweet(
                report=report, client=mock_client, model="claude-sonnet-4-20250514"
            )

    async def test_raises_when_no_tool_use_block(self, mock_client: AsyncMock) -> None:
        text_only = SimpleNamespace(type="text", text="sorry can't do it")
        mock_client.messages.create.return_value = _make_response(text_only)
        report = _minimal_report(best_variant=_best_variant())

        with pytest.raises(LLMError):
            await draft_daily_tweet(
                report=report, client=mock_client, model="claude-sonnet-4-20250514"
            )

    async def test_serializer_includes_best_variant_and_delta(self) -> None:
        report = _minimal_report(
            best_variant=_best_variant(),
            actions=[ReportCycleAction(action_type="pause", variant_code="V3", details=None)],
        )
        serialized = _serialize_report_for_prompt(report)

        assert "urgency headline + direct CTA" in serialized
        assert "V7" in serialized
        assert '"num_actions_taken": 1' in serialized
        # CPA went from 10.0 → 8.33, a 16.7% decrease
        assert "cpa_delta_vs_prev_day" in serialized
        assert "-16.7%" in serialized
