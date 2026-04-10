"""Tests for the Phase F legacy migration (``008_migrate_legacy_campaigns``).

The migration has three steps:

1. SELECT the operator user by email; abort with a clear error if
   missing.
2. UPDATE all ``campaigns`` rows with ``NULL owner_user_id`` to
   reference the operator.
3. ALTER COLUMN ``owner_user_id`` SET NOT NULL.

Rather than spinning up a real Postgres (this repo's integration
tests are all hermetic mocks), we import the migration module
directly and patch the ``alembic.op`` surface it uses. That gives us
a deterministic way to verify the SQL the migration runs without
having to reason about Alembic's bind lifecycle.

The tests cover:

- Happy path: operator exists → SELECT, UPDATE, and ALTER fire in
  order, with the resolved operator ID threaded through the UPDATE.
- Operator missing: SELECT returns NULL → the migration raises
  ``RuntimeError`` with a useful message and NEVER alters the
  column. This is the critical safety property — a missing
  operator must not accidentally produce a NOT NULL column on an
  empty table.
- Downgrade: ALTER COLUMN is called with ``nullable=True``.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest


# ---------------------------------------------------------------------------
# Import the migration module directly (it's not on the Python path).
# ---------------------------------------------------------------------------

MIGRATION_PATH = (
    Path(__file__).resolve().parents[2]
    / "alembic"
    / "versions"
    / "008_migrate_legacy_campaigns.py"
)


def _load_migration():
    """Load the migration module fresh for each test.

    Each call produces a distinct module object so patches don't
    leak between tests.
    """
    spec = importlib.util.spec_from_file_location(
        f"_legacy_migration_{uuid4().hex}", MIGRATION_PATH
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


# ---------------------------------------------------------------------------
# Bind stub — mirrors the small subset of SQLAlchemy's Connection API
# the migration actually touches.
# ---------------------------------------------------------------------------


class _BindStub:
    """Scripted ``execute()`` that returns pre-baked rowsets in order."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.calls: list[tuple[str, dict | None]] = []

    def execute(self, statement, params=None):
        # ``statement`` is a ``sqlalchemy.text(...)`` construct; we
        # grab its ``.text`` attribute so we can assert on the SQL
        # string without getting tangled up in TextClause identity.
        sql = getattr(statement, "text", str(statement))
        self.calls.append((sql, params))
        if not self._responses:
            raise AssertionError(f"Unexpected extra execute: {sql}")
        result = self._responses.pop(0)
        return result


class _ScalarResult:
    """Minimal ``Result`` stand-in that supports ``.scalar()``."""

    def __init__(self, value):
        self._value = value

    def scalar(self):
        return self._value


# ---------------------------------------------------------------------------
# Happy path: operator exists, assignment runs, NOT NULL is applied
# ---------------------------------------------------------------------------


class TestUpgrade:
    def test_happy_path_runs_all_three_steps(self) -> None:
        module = _load_migration()
        operator_id = uuid4()

        bind = _BindStub(
            [
                # Step 1: SELECT operator
                _ScalarResult(operator_id),
                # Step 2: UPDATE campaigns
                _ScalarResult(None),
            ]
        )

        fake_op = MagicMock()
        fake_op.get_bind.return_value = bind

        with patch.object(module, "op", fake_op):
            module.upgrade()

        # 1. Two SQL calls: SELECT then UPDATE.
        assert len(bind.calls) == 2
        select_sql, select_params = bind.calls[0]
        update_sql, update_params = bind.calls[1]

        assert "SELECT id FROM users" in select_sql
        assert select_params == {"email": "esargent01@gmail.com"}

        assert "UPDATE campaigns" in update_sql
        assert "owner_user_id IS NULL" in update_sql
        assert update_params == {"operator_id": operator_id}

        # 2. ALTER COLUMN was issued with nullable=False.
        fake_op.alter_column.assert_called_once()
        call = fake_op.alter_column.call_args
        assert call.args[0] == "campaigns"
        assert call.args[1] == "owner_user_id"
        assert call.kwargs["nullable"] is False

    def test_missing_operator_aborts_before_alter(self) -> None:
        """If the operator user doesn't exist, the migration must
        raise ``RuntimeError`` and never touch the schema."""
        module = _load_migration()

        bind = _BindStub(
            [
                _ScalarResult(None),  # SELECT returns no row
            ]
        )

        fake_op = MagicMock()
        fake_op.get_bind.return_value = bind

        with patch.object(module, "op", fake_op):
            with pytest.raises(RuntimeError, match="esargent01@gmail.com"):
                module.upgrade()

        # Only the SELECT ran.
        assert len(bind.calls) == 1
        assert "SELECT id FROM users" in bind.calls[0][0]

        # Critical invariant: the column was NOT altered. This is
        # what prevents the migration from producing a broken
        # NOT NULL column against a half-migrated table.
        fake_op.alter_column.assert_not_called()

    def test_idempotent_re_run_only_touches_null_rows(self) -> None:
        """The UPDATE must filter on ``WHERE owner_user_id IS NULL``
        so re-running the migration against an already-migrated
        table is a no-op (beyond the SELECT + ALTER).
        """
        module = _load_migration()
        operator_id = uuid4()

        bind = _BindStub(
            [
                _ScalarResult(operator_id),
                _ScalarResult(None),
            ]
        )

        fake_op = MagicMock()
        fake_op.get_bind.return_value = bind

        with patch.object(module, "op", fake_op):
            module.upgrade()

        _, update_sql_params = bind.calls[1]
        assert "WHERE owner_user_id IS NULL" in bind.calls[1][0]
        assert update_sql_params == {"operator_id": operator_id}


# ---------------------------------------------------------------------------
# Downgrade: relaxes NOT NULL; leaves ownership assignments in place
# ---------------------------------------------------------------------------


class TestDowngrade:
    def test_downgrade_drops_not_null(self) -> None:
        module = _load_migration()

        fake_op = MagicMock()
        with patch.object(module, "op", fake_op):
            module.downgrade()

        fake_op.alter_column.assert_called_once()
        call = fake_op.alter_column.call_args
        assert call.args[0] == "campaigns"
        assert call.args[1] == "owner_user_id"
        assert call.kwargs["nullable"] is True
