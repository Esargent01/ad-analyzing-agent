"""Unit tests for the Phase E usage-logging service.

The service module splits cleanly into two concerns:

1. **Cost math** (``calculate_llm_cost``) — a pure function that
   turns a model name + token counts into a Decimal cost. Tests
   here lock down the per-MTok pricing table, the rounding rule,
   the unknown-model fallback, and the non-negative guard.
2. **Logging helpers** (``log_llm_call``, ``log_meta_call``) —
   adds ``UsageLog`` rows to a session. Tests stub out the
   session and assert on what gets staged.

No DB, no network, no real clock.
"""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from src.db.tables import UsageLog
from src.services.usage import (
    SERVICE_LLM,
    SERVICE_META,
    AgentContext,
    PRICING,
    calculate_llm_cost,
    log_llm_call,
    log_meta_call,
)


class TestCalculateLlmCost:
    def test_sonnet_known_model(self) -> None:
        # Sonnet 4.5: $3 input / $15 output per 1M tokens.
        # 1000 input + 500 output tokens:
        # 1000/1e6 * 3 + 500/1e6 * 15 = 0.003 + 0.0075 = 0.0105
        cost = calculate_llm_cost("claude-sonnet-4-5", 1000, 500)
        assert cost == Decimal("0.010500")

    def test_haiku_cheaper_than_sonnet(self) -> None:
        haiku = calculate_llm_cost("claude-haiku-4-5", 10_000, 5_000)
        sonnet = calculate_llm_cost("claude-sonnet-4-5", 10_000, 5_000)
        assert haiku < sonnet

    def test_unknown_model_uses_fallback(self, caplog) -> None:
        """Unknown models must fall back to the Sonnet tier (not $0)."""
        with caplog.at_level("WARNING"):
            cost = calculate_llm_cost("claude-tomorrow-9000", 1000, 500)
        assert cost == Decimal("0.010500")
        assert any("Unknown model" in rec.message for rec in caplog.records)

    def test_zero_tokens_returns_zero(self) -> None:
        assert calculate_llm_cost("claude-sonnet-4-5", 0, 0) == Decimal("0.000000")

    def test_rounds_to_six_decimals(self) -> None:
        """Rounding must be deterministic (quantize to 6 places)."""
        # Use awkward token counts to force a multi-decimal result.
        cost = calculate_llm_cost("claude-sonnet-4-5", 1, 1)
        # 1/1e6 * 3 + 1/1e6 * 15 = 0.000018
        assert cost == Decimal("0.000018")
        assert cost.as_tuple().exponent == -6

    def test_negative_tokens_rejected(self) -> None:
        with pytest.raises(ValueError, match="non-negative"):
            calculate_llm_cost("claude-sonnet-4-5", -1, 500)
        with pytest.raises(ValueError, match="non-negative"):
            calculate_llm_cost("claude-sonnet-4-5", 500, -1)

    def test_large_request_scales_linearly(self) -> None:
        """Doubling tokens must double cost (pure proportionality)."""
        small = calculate_llm_cost("claude-sonnet-4-5", 1000, 500)
        big = calculate_llm_cost("claude-sonnet-4-5", 2000, 1000)
        assert big == small * 2

    def test_pricing_table_has_known_entries(self) -> None:
        """Guard against accidental deletes in the pricing table."""
        assert "claude-sonnet-4-5" in PRICING
        assert "claude-haiku-4-5" in PRICING
        # Input must always be cheaper than output.
        for model, (in_rate, out_rate) in PRICING.items():
            assert in_rate < out_rate, f"{model}: input ≥ output price"


class TestAgentContext:
    def test_defaults_are_none(self) -> None:
        ctx = AgentContext()
        assert ctx.user_id is None
        assert ctx.campaign_id is None
        assert ctx.cycle_id is None
        assert ctx.agent is None

    def test_frozen_dataclass(self) -> None:
        """Context is immutable so it's safe to share across coroutines."""
        ctx = AgentContext(agent="generator")
        with pytest.raises(Exception):
            ctx.agent = "analyst"  # type: ignore[misc]


class TestLogLlmCall:
    async def test_stages_row_with_cost_and_context(self) -> None:
        session = AsyncMock()
        added: list[object] = []
        session.add = lambda obj: added.append(obj)

        user_id = uuid4()
        campaign_id = uuid4()
        cycle_id = uuid4()
        ctx = AgentContext(
            user_id=user_id,
            campaign_id=campaign_id,
            cycle_id=cycle_id,
            agent="generator",
        )

        row = await log_llm_call(
            session,
            ctx,
            model="claude-sonnet-4-5",
            input_tokens=2000,
            output_tokens=1000,
        )

        assert isinstance(row, UsageLog)
        assert len(added) == 1
        logged = added[0]
        assert isinstance(logged, UsageLog)
        assert logged.service == SERVICE_LLM
        assert logged.agent == "generator"
        assert logged.model == "claude-sonnet-4-5"
        assert logged.input_units == 2000
        assert logged.output_units == 1000
        # 2000/1e6*3 + 1000/1e6*15 = 0.006 + 0.015 = 0.021
        assert logged.cost_usd == Decimal("0.021000")
        assert logged.user_id == user_id
        assert logged.campaign_id == campaign_id
        assert logged.cycle_id == cycle_id

    async def test_nulls_when_ctx_is_empty(self) -> None:
        """Maintenance / CLI calls that have no owning user should
        still produce a row with NULL FKs — the service-level
        aggregate still counts them."""
        session = AsyncMock()
        added: list[object] = []
        session.add = lambda obj: added.append(obj)

        ctx = AgentContext()  # all None
        await log_llm_call(
            session, ctx, model="claude-sonnet-4-5", input_tokens=100, output_tokens=50
        )

        assert len(added) == 1
        row = added[0]
        assert isinstance(row, UsageLog)
        assert row.user_id is None
        assert row.campaign_id is None
        assert row.cycle_id is None
        assert row.agent is None
        assert row.cost_usd > Decimal("0")

    async def test_metadata_passthrough(self) -> None:
        session = AsyncMock()
        added: list[object] = []
        session.add = lambda obj: added.append(obj)

        ctx = AgentContext(agent="analyst")
        await log_llm_call(
            session,
            ctx,
            model="claude-sonnet-4-5",
            input_tokens=10,
            output_tokens=5,
            metadata={"stop_reason": "end_turn"},
        )
        assert added[0].metadata_json == {"stop_reason": "end_turn"}  # type: ignore[attr-defined]


class TestLogMetaCall:
    async def test_defaults_to_zero_cost(self) -> None:
        session = AsyncMock()
        added: list[object] = []
        session.add = lambda obj: added.append(obj)

        ctx = AgentContext(campaign_id=uuid4())
        await log_meta_call(session, ctx, method="create_ad")

        assert len(added) == 1
        row = added[0]
        assert isinstance(row, UsageLog)
        assert row.service == SERVICE_META
        assert row.cost_usd == Decimal("0")
        assert row.model is None
        assert row.input_units == 0
        assert row.output_units == 0
        assert row.metadata_json == {"method": "create_ad"}  # type: ignore[comparison-overlap]

    async def test_method_is_always_in_metadata(self) -> None:
        session = AsyncMock()
        added: list[object] = []
        session.add = lambda obj: added.append(obj)

        ctx = AgentContext()
        await log_meta_call(
            session,
            ctx,
            method="get_metrics",
            metadata={"variant_id": "v1"},
        )
        meta = added[0].metadata_json  # type: ignore[attr-defined]
        assert meta == {"method": "get_metrics", "variant_id": "v1"}

    async def test_explicit_cost_is_logged(self) -> None:
        session = AsyncMock()
        added: list[object] = []
        session.add = lambda obj: added.append(obj)

        ctx = AgentContext()
        await log_meta_call(
            session,
            ctx,
            method="create_ad",
            cost_usd=Decimal("0.0025"),
        )
        assert added[0].cost_usd == Decimal("0.0025")  # type: ignore[attr-defined]
