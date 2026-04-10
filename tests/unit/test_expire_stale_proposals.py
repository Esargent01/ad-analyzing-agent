"""Tests for the expire_stale_proposals TTL helper."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.db.queries import expire_stale_proposals
from src.db.tables import ApprovalActionType, VariantStatus


def _make_item(
    days_old: int,
    action_type: ApprovalActionType = ApprovalActionType.new_variant,
) -> SimpleNamespace:
    """Build a mock ApprovalQueueItem that behaves like the ORM row."""
    return SimpleNamespace(
        id=uuid.uuid4(),
        variant_id=uuid.uuid4(),
        campaign_id=uuid.uuid4(),
        submitted_at=datetime.now(UTC) - timedelta(days=days_old),
        approved=None,
        reviewed_at=None,
        reviewer=None,
        rejection_reason=None,
        action_type=action_type,
        action_payload={},
    )


def _make_variant() -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.uuid4(),
        status=VariantStatus.pending,
        retired_at=None,
    )


def _make_session(stale_items: list[SimpleNamespace]) -> AsyncMock:
    """Build a mock session whose .execute returns *stale_items* as scalars."""
    session = AsyncMock()
    session.flush = AsyncMock()

    # session.execute(...) -> result where result.scalars().all() == stale_items
    scalars = MagicMock()
    scalars.all.return_value = stale_items
    result = MagicMock()
    result.scalars.return_value = scalars
    session.execute = AsyncMock(return_value=result)

    # session.get(Variant, id) -> a fresh mock variant each time
    async def _fake_get(*args, **kwargs):  # noqa: ANN001
        return _make_variant()

    session.get = AsyncMock(side_effect=_fake_get)
    return session


class TestExpireStaleProposals:
    @pytest.mark.asyncio
    async def test_returns_zero_when_nothing_stale(self) -> None:
        session = _make_session(stale_items=[])
        campaign_id = uuid.uuid4()
        result = await expire_stale_proposals(session, campaign_id, ttl_days=14)
        assert result == 0

    @pytest.mark.asyncio
    async def test_marks_each_item_rejected(self) -> None:
        stale = [_make_item(days_old=15), _make_item(days_old=30)]
        session = _make_session(stale_items=stale)
        campaign_id = uuid.uuid4()

        result = await expire_stale_proposals(session, campaign_id, ttl_days=14)

        assert result == 2
        for item in stale:
            assert item.approved is False
            assert item.reviewer == "system"
            assert item.rejection_reason == "expired_no_review"
            assert item.reviewed_at is not None

    @pytest.mark.asyncio
    async def test_flushes_session(self) -> None:
        session = _make_session(stale_items=[_make_item(days_old=20)])
        await expire_stale_proposals(session, uuid.uuid4(), ttl_days=14)
        session.flush.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_retires_associated_variants(self) -> None:
        """Each stale item should result in a variant lookup and retirement."""
        stale = [_make_item(days_old=16), _make_item(days_old=20)]
        retired: list[SimpleNamespace] = []

        session = AsyncMock()
        session.flush = AsyncMock()

        scalars = MagicMock()
        scalars.all.return_value = stale
        exec_result = MagicMock()
        exec_result.scalars.return_value = scalars
        session.execute = AsyncMock(return_value=exec_result)

        async def _get_variant(*args, **kwargs):  # noqa: ANN001
            v = _make_variant()
            retired.append(v)
            return v

        session.get = AsyncMock(side_effect=_get_variant)

        count = await expire_stale_proposals(session, uuid.uuid4(), ttl_days=14)

        assert count == 2
        assert len(retired) == 2
        for variant in retired:
            assert variant.status == VariantStatus.retired
            assert variant.retired_at is not None

    @pytest.mark.asyncio
    async def test_ttl_days_is_customizable(self) -> None:
        """ttl_days parameter should be passed through without error.

        The select clause uses the value; with a mocked execute we just
        verify it runs and returns the right count for any TTL.
        """
        stale = [_make_item(days_old=8)]
        session = _make_session(stale_items=stale)
        # 7-day TTL treats the 8-day-old item as stale
        result = await expire_stale_proposals(session, uuid.uuid4(), ttl_days=7)
        assert result == 1

    @pytest.mark.asyncio
    async def test_handles_missing_variant_gracefully(self) -> None:
        """If session.get returns None, the item is still marked rejected."""
        stale = [_make_item(days_old=20)]
        session = AsyncMock()
        session.flush = AsyncMock()

        scalars = MagicMock()
        scalars.all.return_value = stale
        exec_result = MagicMock()
        exec_result.scalars.return_value = scalars
        session.execute = AsyncMock(return_value=exec_result)
        session.get = AsyncMock(return_value=None)  # variant already deleted

        count = await expire_stale_proposals(session, uuid.uuid4(), ttl_days=14)

        assert count == 1
        assert stale[0].approved is False
        assert stale[0].rejection_reason == "expired_no_review"
