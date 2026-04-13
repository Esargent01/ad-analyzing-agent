"""Unit tests for budget guardrails in queue_scale_proposal and _execute_scale.

Validates that:
1. queue_scale_proposal rejects budgets exceeding the campaign daily limit
2. queue_scale_proposal rejects increases exceeding remaining capacity
3. queue_scale_proposal accepts valid proposals within limits
4. _execute_scale re-validates before calling Meta (defense in depth)
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.db.tables import ApprovalQueueItem
from src.exceptions import BudgetExceededError


@pytest.fixture()
def mock_session() -> AsyncMock:
    return AsyncMock()


class TestQueueScaleProposalBudgetValidation:
    """Budget validation in queue_scale_proposal."""

    @pytest.mark.asyncio()
    async def test_rejects_proposed_budget_exceeding_campaign_limit(
        self, mock_session: AsyncMock
    ) -> None:
        from src.db.queries import queue_scale_proposal

        campaign_id = uuid.uuid4()
        deployment_id = uuid.uuid4()

        # has_open_proposal returns False (no existing proposal)
        # campaign.daily_budget = 100
        call_count = 0

        async def _fake_execute(stmt, params=None):
            nonlocal call_count
            call_count += 1
            result = MagicMock()
            if call_count == 1:
                # has_open_proposal query → no open proposals
                result.scalar_one_or_none.return_value = None
            elif call_count == 2:
                # campaign daily_budget query
                result.scalar_one_or_none.return_value = Decimal("100.00")
            return result

        mock_session.execute = AsyncMock(side_effect=_fake_execute)

        with pytest.raises(BudgetExceededError, match="exceeds campaign daily limit"):
            await queue_scale_proposal(
                mock_session,
                campaign_id=campaign_id,
                deployment_id=deployment_id,
                platform_ad_id="mock-ad-123",
                current_budget=Decimal("50.00"),
                proposed_budget=Decimal("150.00"),  # > 100 campaign limit
                evidence={"reason": "test"},
            )

    @pytest.mark.asyncio()
    async def test_rejects_increase_exceeding_remaining_capacity(
        self, mock_session: AsyncMock
    ) -> None:
        from src.db.queries import queue_scale_proposal

        campaign_id = uuid.uuid4()
        deployment_id = uuid.uuid4()

        call_count = 0

        async def _fake_execute(stmt, params=None):
            nonlocal call_count
            call_count += 1
            result = MagicMock()
            if call_count == 1:
                # has_open_proposal → no open proposals
                result.scalar_one_or_none.return_value = None
            elif call_count == 2:
                # campaign daily_budget = 100
                result.scalar_one_or_none.return_value = Decimal("100.00")
            return result

        mock_session.execute = AsyncMock(side_effect=_fake_execute)

        # Mock get_remaining_budget to return 20 (so a +30 increase fails)
        with (
            patch(
                "src.db.queries.get_remaining_budget",
                new=AsyncMock(return_value=Decimal("20.00")),
            ),
            pytest.raises(BudgetExceededError, match="remaining"),
        ):
            await queue_scale_proposal(
                mock_session,
                campaign_id=campaign_id,
                deployment_id=deployment_id,
                platform_ad_id="mock-ad-123",
                current_budget=Decimal("50.00"),
                proposed_budget=Decimal("80.00"),  # +30 increase > 20 remaining
                evidence={"reason": "test"},
            )


class TestExecuteScaleBudgetValidation:
    """Defense-in-depth validation in _execute_scale."""

    @pytest.mark.asyncio()
    async def test_rejects_budget_exceeding_campaign_limit(self) -> None:
        from src.services.approval_executor import ApprovalExecutionError, _execute_scale

        session = AsyncMock()
        adapter = AsyncMock()

        # Campaign daily_budget = 100, proposed = 200
        result = MagicMock()
        result.scalar_one_or_none.return_value = Decimal("100.00")
        session.execute.return_value = result

        item = MagicMock(spec=ApprovalQueueItem)
        item.campaign_id = uuid.uuid4()
        item.action_payload = {
            "platform_ad_id": "mock-ad-123",
            "proposed_budget": 200.0,
            "deployment_id": str(uuid.uuid4()),
        }

        with pytest.raises(ApprovalExecutionError, match="exceeds campaign daily limit"):
            await _execute_scale(session, adapter, item)

        # Verify Meta was NOT called
        adapter.update_budget.assert_not_called()

    @pytest.mark.asyncio()
    async def test_allows_budget_within_limit(self) -> None:
        from src.services.approval_executor import _execute_scale

        session = AsyncMock()
        adapter = AsyncMock()

        # Campaign daily_budget = 100, proposed = 80
        result = MagicMock()
        result.scalar_one_or_none.return_value = Decimal("100.00")
        session.execute.return_value = result

        item = MagicMock(spec=ApprovalQueueItem)
        item.campaign_id = uuid.uuid4()
        item.action_payload = {
            "platform_ad_id": "mock-ad-123",
            "proposed_budget": 80.0,
            "deployment_id": str(uuid.uuid4()),
        }

        await _execute_scale(session, adapter, item)

        # Verify Meta WAS called with the proposed budget
        adapter.update_budget.assert_called_once_with("mock-ad-123", 80.0)
