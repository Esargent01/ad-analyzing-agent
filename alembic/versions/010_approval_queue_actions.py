"""Phase H: multi-action approval queue.

Before this migration ``approval_queue`` could only represent a
"proposed new variant" — every row carried a NOT NULL ``variant_id``
and a ``genome_snapshot``, and the orchestrator's ``_phase_act`` just
went ahead and called ``adapter.pause_ad`` / ``adapter.update_budget``
without asking anyone. Phase H changes that: pause/scale/promote
decisions are now proposals that flow through the same approval
queue, so the human stays in the loop for every Meta mutation.

What this migration does:

1. Adds an ``action_type`` enum column (defaults to ``new_variant`` to
   keep existing rows meaningful) with four kinds:
   - ``new_variant`` — existing behaviour, variant_id required
   - ``pause_variant`` — pause an active ad; payload carries the
     deployment id + reason + evidence
   - ``scale_budget`` — adjust an ad set's daily budget; payload
     carries old + new budget and the posterior evidence
   - ``promote_winner`` — mark a winner variant (future-facing; the
     column is included so the enum is forward-compatible)

2. Adds an ``action_payload JSONB`` column. It's NOT NULL with a
   ``'{}'::jsonb`` default so existing ``new_variant`` rows stay
   valid after the upgrade. Payload shapes for non-variant actions
   are documented on the Pydantic models in ``src/models/approvals.py``.

3. Adds an ``executed_at TIMESTAMPTZ`` column — set by the approval
   executor when it has actually pushed the side-effect to Meta. A
   row with ``approved=TRUE AND executed_at IS NULL`` is the narrow
   window where the DB says approved but the Meta mutation hasn't
   landed yet; the approve handler checks it to make double-click
   idempotent.

4. Drops ``NOT NULL`` from ``variant_id`` so pause/scale rows can
   reference a deployment without pretending to own a variant row.
   A partial CHECK constraint enforces the action-shape invariant:
   new_variant + promote_winner still require variant_id, while
   pause_variant + scale_budget require a ``deployment_id`` key in
   the payload. This is the single source of truth — the service
   layer trusts it and doesn't re-validate.

Downgrade path: drop the check, drop the new columns, re-add
``NOT NULL`` on ``variant_id``. Safe because the default for
action_type is ``new_variant``, which means every existing row had a
variant_id to begin with.

Revision ID: 010_approval_queue_actions
Revises: 009_per_user_meta_tenancy
Create Date: 2026-04-10
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "010_approval_queue_actions"
down_revision: str | None = "009_per_user_meta_tenancy"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


APPROVAL_ACTION_TYPES = (
    "new_variant",
    "pause_variant",
    "scale_budget",
    "promote_winner",
)


def upgrade() -> None:
    # ------------------------------------------------------------------
    # Step 1 — create the action_type enum. Using a dedicated name
    # (``approval_action_type``) so it doesn't collide with the
    # existing ``action_type`` enum on ``cycle_actions`` (which
    # tracks audit-log actions, a different vocabulary).
    # ------------------------------------------------------------------
    approval_action_enum = postgresql.ENUM(
        *APPROVAL_ACTION_TYPES,
        name="approval_action_type",
        create_type=True,
    )
    approval_action_enum.create(op.get_bind(), checkfirst=True)

    # ------------------------------------------------------------------
    # Step 2 — add the new columns with safe defaults. Every existing
    # row becomes ``new_variant`` with an empty payload and no
    # executed_at — matching its prior meaning exactly.
    # ------------------------------------------------------------------
    op.add_column(
        "approval_queue",
        sa.Column(
            "action_type",
            postgresql.ENUM(
                *APPROVAL_ACTION_TYPES,
                name="approval_action_type",
                create_type=False,
            ),
            nullable=False,
            server_default="new_variant",
        ),
    )
    op.add_column(
        "approval_queue",
        sa.Column(
            "action_payload",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )
    op.add_column(
        "approval_queue",
        sa.Column(
            "executed_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )

    # ------------------------------------------------------------------
    # Step 3 — relax variant_id so pause/scale rows can exist without
    # a synthetic variant row. The partial CHECK below guarantees
    # variant_id is still required for row types that semantically
    # need it.
    # ------------------------------------------------------------------
    op.alter_column("approval_queue", "variant_id", nullable=True)

    # ------------------------------------------------------------------
    # Step 4 — partial CHECK enforcing per-action-type shape. Pure
    # SQL rather than a trigger so PG's query planner can see it and
    # so rollback is trivial.
    # ------------------------------------------------------------------
    op.create_check_constraint(
        "approval_queue_action_shape_check",
        "approval_queue",
        "(action_type IN ('new_variant', 'promote_winner') AND variant_id IS NOT NULL) "
        "OR (action_type IN ('pause_variant', 'scale_budget') AND action_payload ? 'deployment_id')",
    )

    # ------------------------------------------------------------------
    # Step 5 — index pending rows by (campaign_id, action_type) so the
    # digest query that counts-by-type for each owner stays cheap at
    # any realistic queue size. Partial index: only pending rows, same
    # pattern as the existing ``idx_approval_pending``.
    # ------------------------------------------------------------------
    op.create_index(
        "idx_approval_pending_by_type",
        "approval_queue",
        ["campaign_id", "action_type"],
        postgresql_where=sa.text("approved IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("idx_approval_pending_by_type", table_name="approval_queue")
    op.drop_constraint("approval_queue_action_shape_check", "approval_queue", type_="check")

    # Before re-adding NOT NULL on variant_id we must delete any rows
    # that don't have one — those are pause/scale proposals Phase H
    # introduced. A downgrade that throws away Phase H rows is
    # preferable to one that leaves a constraint violation.
    op.execute("DELETE FROM approval_queue WHERE variant_id IS NULL")
    op.alter_column("approval_queue", "variant_id", nullable=False)

    op.drop_column("approval_queue", "executed_at")
    op.drop_column("approval_queue", "action_payload")
    op.drop_column("approval_queue", "action_type")

    approval_action_enum = postgresql.ENUM(
        *APPROVAL_ACTION_TYPES,
        name="approval_action_type",
        create_type=False,
    )
    approval_action_enum.drop(op.get_bind(), checkfirst=True)
