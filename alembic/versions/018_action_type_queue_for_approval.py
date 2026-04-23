"""Add 'queue_for_approval' value to the ``action_type`` Postgres enum.

Revision ID: 018_action_type_queue
Revises: 017_campaign_objective
Create Date: 2026-04-23

Phase H added a ``queue_for_approval`` value to the Python
:class:`src.db.tables.ActionType` enum so the orchestrator's
propose-step could write an audit row to ``cycle_actions`` whenever
it queued a pause / scale / new-variant proposal — but no matching
``ALTER TYPE`` migration shipped, leaving the Postgres enum stuck
on its initial values (``launch, pause, increase_budget,
decrease_budget, retire, promote_winner``).

Symptom: every daily cron run for every active user-owned campaign
errored with::

    invalid input value for enum action_type: "queue_for_approval"

… on the very first ``INSERT INTO cycle_actions`` of the propose
phase. The whole cycle rolled back, no ``test_cycles`` / no
``approval_queue`` rows were written, and the campaign silently sat
without recommendations forever. Confirmed in the daily-cron
GitHub-Actions logs from 2026-04-22 onward.

Fix: ``ALTER TYPE action_type ADD VALUE IF NOT EXISTS
'queue_for_approval'``. Postgres requires this to run outside a
transaction (``ALTER TYPE`` on enums is not transactional in
modern PG), so the operation is wrapped in
``op.execute(... AUTOCOMMIT)``.

Downgrade is intentionally a no-op: Postgres doesn't support
removing values from an existing enum without a full type
rewrite, and any existing rows referencing the value would block
the rewrite anyway. Re-running the upgrade after a downgrade is
safe because of the ``IF NOT EXISTS`` guard.
"""

from alembic import op

revision = "018_action_type_queue"
down_revision = "017_campaign_objective"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ALTER TYPE ADD VALUE must run outside a transaction in PG.
    # Use AUTOCOMMIT isolation so this DDL doesn't sit inside the
    # default migration transaction.
    with op.get_context().autocommit_block():
        op.execute(
            "ALTER TYPE action_type ADD VALUE IF NOT EXISTS 'queue_for_approval'"
        )


def downgrade() -> None:
    # PG can't drop enum values cleanly; leave the value in place.
    pass
