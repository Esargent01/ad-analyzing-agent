"""Phase H regression tests: propose-only orchestrator + executor dispatch.

These tests guard the Phase H invariant that the orchestrator cycle
path never directly mutates Meta. Every pause / scale / promote action
now lands in ``approval_queue`` as a proposal, and the executor is the
only code path that calls ``MetaAdapter.pause_ad`` or ``update_budget``
— and only after a user has clicked Approve.

The tests split into three layers:

1. **Static invariant** — read ``src/services/orchestrator.py`` and
   assert no ``adapter.pause_ad`` / ``adapter.update_budget`` substrings
   in the file. This is the cheapest possible guardrail and matches
   the grep-level acceptance criterion from the Phase H plan.
2. **Runtime propose-only** — run a full ``Orchestrator.run_cycle``
   with an ``AsyncMock``-wrapped adapter and assert those two methods
   were never awaited during the cycle.
3. **Executor dispatch** — exercise ``execute_approved_action`` across
   every meaningful control path: missing row, not-yet-approved,
   already-executed (double-click), pause happy path, scale happy
   path, and Meta-failure rollback.

No real database is involved — the executor tests stub
``session.get`` and ``session.execute`` the same way the existing
``tests/integration/test_orchestrator.py`` does. This matches the
project's integration-test style (mocks, not docker-compose) and keeps
the suite fast enough to run on every push.
"""

from __future__ import annotations

import ast
import uuid
from datetime import UTC
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.adapters.mock import MockAdapter
from src.db.tables import ApprovalActionType, ApprovalQueueItem
from src.exceptions import MetaConnectionMissing
from src.services.approval_executor import execute_approved_action
from src.services.orchestrator import Orchestrator

PROJECT_ROOT = Path(__file__).resolve().parents[2]
ORCHESTRATOR_FILE = PROJECT_ROOT / "src" / "services" / "orchestrator.py"


# ---------------------------------------------------------------------------
# Shared helpers (lifted from test_orchestrator.py)
# ---------------------------------------------------------------------------


def _make_settings(**overrides: object) -> SimpleNamespace:
    defaults = {
        "min_impressions": 1000,
        "confidence_threshold": 0.95,
        "max_concurrent_variants": 10,
        "anthropic_api_key": "sk-test",
        "anthropic_model": "claude-sonnet-4-20250514",
        "log_level": "DEBUG",
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def _make_mock_session_factory() -> tuple[async_sessionmaker, AsyncMock]:
    mock_session = AsyncMock(spec=AsyncSession)
    mock_result = MagicMock()
    mock_result.fetchone.return_value = (1,)
    mock_result.fetchall.return_value = []
    mock_session.execute.return_value = mock_result
    mock_session.flush = AsyncMock()
    mock_session.commit = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    factory = MagicMock(spec=async_sessionmaker)
    factory.return_value = mock_session
    return factory, mock_session


# ---------------------------------------------------------------------------
# 1. Static invariant
# ---------------------------------------------------------------------------


def _collect_method_calls(tree: ast.AST) -> set[str]:
    """Return the set of ``<something>.<method>`` names that appear as
    call targets anywhere in an AST.

    We walk the tree looking for ``Call(func=Attribute(...))`` nodes
    and yield ``attr`` for each one. Good enough to spot
    ``self._adapter.pause_ad(...)`` without tripping on substrings
    inside docstrings or comments.
    """
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            names.add(node.func.attr)
    return names


class TestProposeOnlyStaticInvariant:
    """The cycle path source must not *call* Meta mutation methods.

    Parses ``src/services/orchestrator.py`` with ``ast`` and walks
    every ``Call(func=Attribute(...))`` node. Phase H requires that
    ``pause_ad`` and ``update_budget`` never appear as called
    attributes anywhere in the orchestrator — every mutation goes
    through ``approval_queue``. Docstrings that *describe* the
    refactor are allowed; actual calls are not.
    """

    def test_orchestrator_never_calls_pause_ad(self) -> None:
        tree = ast.parse(ORCHESTRATOR_FILE.read_text())
        method_calls = _collect_method_calls(tree)
        assert "pause_ad" not in method_calls, (
            "Orchestrator must not call .pause_ad() directly — "
            "pause proposals go through approval_queue in Phase H."
        )

    def test_orchestrator_never_calls_update_budget(self) -> None:
        tree = ast.parse(ORCHESTRATOR_FILE.read_text())
        method_calls = _collect_method_calls(tree)
        assert "update_budget" not in method_calls, (
            "Orchestrator must not call .update_budget() directly — "
            "scale proposals go through approval_queue in Phase H."
        )


# ---------------------------------------------------------------------------
# 2. Runtime propose-only
# ---------------------------------------------------------------------------


class TestRuntimeProposeOnly:
    """A full run_cycle with a spy adapter never touches pause/budget."""

    async def test_run_cycle_never_awaits_pause_ad_or_update_budget(self) -> None:
        # Wrap the adapter methods in AsyncMock so we can assert on
        # await history. The MockAdapter's real pause_ad/update_budget
        # are trivial stubs so the replacement doesn't change behavior.
        adapter = MockAdapter(seed=42)
        adapter.pause_ad = AsyncMock(return_value=True)  # type: ignore[method-assign]
        adapter.update_budget = AsyncMock(return_value=True)  # type: ignore[method-assign]

        factory, _ = _make_mock_session_factory()
        settings = _make_settings()

        orchestrator = Orchestrator(
            adapter=adapter,
            session_factory=factory,
            settings=settings,
        )
        await orchestrator.run_cycle(uuid.uuid4())

        # The cycle path must route every mutation through the
        # approval queue, not straight to Meta.
        adapter.pause_ad.assert_not_awaited()
        adapter.update_budget.assert_not_awaited()


# ---------------------------------------------------------------------------
# 3. Executor dispatch
# ---------------------------------------------------------------------------


def _make_approval_row(
    *,
    action_type: ApprovalActionType,
    approved: bool | None = True,
    executed_at=None,
    payload: dict | None = None,
    campaign_id: uuid.UUID | None = None,
) -> ApprovalQueueItem:
    """Build an ApprovalQueueItem SimpleNamespace-style stub.

    We can't instantiate the ORM class without a session binding, so
    we return a ``SimpleNamespace`` that exposes the attributes the
    executor reads. Cast to the ORM type for type checking only.
    """
    return SimpleNamespace(  # type: ignore[return-value]
        id=uuid.uuid4(),
        campaign_id=campaign_id or uuid.uuid4(),
        action_type=action_type,
        approved=approved,
        executed_at=executed_at,
        action_payload=payload or {},
        rejection_reason=None,
    )


class TestExecutorDispatch:
    """Executor dispatch for each code path in the Phase H plan.

    Covers:
    - Missing row → ok=False, message references "not found"
    - Not yet approved → ok=False, "not in an approved state"
    - Already executed (double-click) → ok=True without new side-effects
    - Pause happy path → adapter.pause_ad awaited with platform_ad_id
    - Scale happy path → adapter.update_budget awaited with float budget
    - Meta failure → row rolled back to approved=False with meta_error prefix
    - MetaConnectionMissing at factory → row rolled back, ok=False
    """

    async def test_missing_row_returns_not_found(self) -> None:
        session = AsyncMock(spec=AsyncSession)
        session.get = AsyncMock(return_value=None)

        result = await execute_approved_action(session, approval_id=uuid.uuid4())

        assert result.ok is False
        assert "not found" in result.message.lower()

    async def test_not_yet_approved_returns_error(self) -> None:
        session = AsyncMock(spec=AsyncSession)
        row = _make_approval_row(
            action_type=ApprovalActionType.pause_variant,
            approved=None,  # still pending
            payload={"deployment_id": str(uuid.uuid4()), "platform_ad_id": "123_456"},
        )
        session.get = AsyncMock(return_value=row)

        result = await execute_approved_action(session, approval_id=row.id)

        assert result.ok is False
        assert "approved state" in result.message.lower()

    async def test_already_executed_is_idempotent(self) -> None:
        session = AsyncMock(spec=AsyncSession)
        from datetime import datetime

        row = _make_approval_row(
            action_type=ApprovalActionType.pause_variant,
            approved=True,
            executed_at=datetime.now(UTC),
            payload={"deployment_id": str(uuid.uuid4()), "platform_ad_id": "123_456"},
        )
        session.get = AsyncMock(return_value=row)

        result = await execute_approved_action(session, approval_id=row.id)

        assert result.ok is True
        assert "already executed" in result.message.lower()

    async def test_pause_happy_path_calls_adapter(self) -> None:
        session = AsyncMock(spec=AsyncSession)
        session.execute = AsyncMock()

        deployment_id = uuid.uuid4()
        row = _make_approval_row(
            action_type=ApprovalActionType.pause_variant,
            approved=True,
            payload={
                "deployment_id": str(deployment_id),
                "platform_ad_id": "act_123_456",
            },
        )
        session.get = AsyncMock(return_value=row)

        adapter = MagicMock()
        adapter.pause_ad = AsyncMock(return_value=True)

        with (
            patch(
                "src.services.approval_executor.get_meta_adapter_for_campaign",
                new=AsyncMock(return_value=adapter),
            ),
            patch(
                "src.services.approval_executor.mark_proposal_executed",
                new=AsyncMock(),
            ) as mark_mock,
        ):
            result = await execute_approved_action(session, approval_id=row.id)

        assert result.ok is True
        adapter.pause_ad.assert_awaited_once_with("act_123_456")
        mark_mock.assert_awaited_once()

    async def test_scale_happy_path_calls_adapter_with_float(self) -> None:
        session = AsyncMock(spec=AsyncSession)
        session.execute = AsyncMock()

        deployment_id = uuid.uuid4()
        row = _make_approval_row(
            action_type=ApprovalActionType.scale_budget,
            approved=True,
            payload={
                "deployment_id": str(deployment_id),
                "platform_ad_id": "act_999",
                "current_budget": 25.0,
                "proposed_budget": 40.0,
            },
        )
        session.get = AsyncMock(return_value=row)

        adapter = MagicMock()
        adapter.update_budget = AsyncMock(return_value=True)

        with (
            patch(
                "src.services.approval_executor.get_meta_adapter_for_campaign",
                new=AsyncMock(return_value=adapter),
            ),
            patch(
                "src.services.approval_executor.mark_proposal_executed",
                new=AsyncMock(),
            ),
        ):
            result = await execute_approved_action(session, approval_id=row.id)

        assert result.ok is True
        adapter.update_budget.assert_awaited_once()
        (args, _kwargs) = adapter.update_budget.await_args
        assert args[0] == "act_999"
        assert isinstance(args[1], float)
        assert args[1] == pytest.approx(40.0)

    async def test_meta_failure_rolls_back_with_reason(self) -> None:
        session = AsyncMock(spec=AsyncSession)
        session.execute = AsyncMock()
        session.flush = AsyncMock()

        row = _make_approval_row(
            action_type=ApprovalActionType.pause_variant,
            approved=True,
            payload={
                "deployment_id": str(uuid.uuid4()),
                "platform_ad_id": "act_broken",
            },
        )
        session.get = AsyncMock(return_value=row)

        adapter = MagicMock()
        adapter.pause_ad = AsyncMock(side_effect=RuntimeError("meta is angry"))

        with patch(
            "src.services.approval_executor.get_meta_adapter_for_campaign",
            new=AsyncMock(return_value=adapter),
        ):
            result = await execute_approved_action(session, approval_id=row.id)

        assert result.ok is False
        # Row should have been flipped back to rejected for audit.
        assert row.approved is False
        assert row.rejection_reason is not None
        assert row.rejection_reason.startswith("meta_error:")

    async def test_meta_connection_missing_rolls_back(self) -> None:
        session = AsyncMock(spec=AsyncSession)
        session.flush = AsyncMock()

        row = _make_approval_row(
            action_type=ApprovalActionType.pause_variant,
            approved=True,
            payload={
                "deployment_id": str(uuid.uuid4()),
                "platform_ad_id": "act_orphan",
            },
        )
        session.get = AsyncMock(return_value=row)

        with patch(
            "src.services.approval_executor.get_meta_adapter_for_campaign",
            new=AsyncMock(side_effect=MetaConnectionMissing("no connection")),
        ):
            result = await execute_approved_action(session, approval_id=row.id)

        assert result.ok is False
        assert row.approved is False
        assert row.rejection_reason is not None
        assert row.rejection_reason.startswith("meta_connection_error:")
