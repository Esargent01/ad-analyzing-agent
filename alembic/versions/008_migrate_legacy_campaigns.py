"""Assign legacy campaigns to esargent01@gmail.com and enforce owner_user_id.

Phase F of the self-serve multi-tenant migration. Closes the loop on
the per-user architecture by guaranteeing every campaign has an
``owner_user_id`` and that the column is ``NOT NULL``.

Why this needs to run as a dedicated migration:

- Phase C added ``campaigns.owner_user_id`` as nullable so the
  ``_legacy_global_adapter`` fallback could keep unowned campaigns
  running during the transition.
- Phase D introduced self-serve imports, which *do* set the owner.
- Phase F (this migration) backfills every row that still has
  ``NULL`` to the operator account (``esargent01@gmail.com``) so the
  column can finally be enforced ``NOT NULL`` and the Phase C
  fallback code path deleted.

Safety properties:

- Assignment is conditional on the operator user existing. If the
  ``users`` table has no row with that email, the upgrade aborts
  with a clear error rather than silently skipping rows. That's the
  right failure mode — a missing operator account is a deployment
  misconfiguration, not a data migration concern.
- The ``NOT NULL`` constraint is only applied after the UPDATE, so
  we never briefly violate our own invariant.
- Downgrade is reversible: drop the ``NOT NULL``, but leave the
  assignments in place. If someone rolls back they still benefit
  from the ownership backfill.

Revision ID: 008_migrate_legacy_campaigns
Revises: 007_usage_log
Create Date: 2026-04-09

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = "008_migrate_legacy_campaigns"
down_revision: Union[str, None] = "007_usage_log"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


LEGACY_OWNER_EMAIL = "esargent01@gmail.com"


def upgrade() -> None:
    bind = op.get_bind()

    # Step 1 — resolve the operator user. If missing, abort with a
    # clear error so the deployer can seed the account before retrying.
    operator_id = bind.execute(
        sa.text("SELECT id FROM users WHERE email = :email"),
        {"email": LEGACY_OWNER_EMAIL},
    ).scalar()

    if operator_id is None:
        raise RuntimeError(
            f"Cannot migrate legacy campaigns: user {LEGACY_OWNER_EMAIL!r} "
            "does not exist. Create the account first, then re-run this "
            "migration."
        )

    # Step 2 — assign every orphan campaign to the operator. Only
    # touches rows that still have NULL so re-runs are idempotent.
    bind.execute(
        sa.text(
            """
            UPDATE campaigns
            SET owner_user_id = :operator_id
            WHERE owner_user_id IS NULL
            """
        ),
        {"operator_id": operator_id},
    )

    # Step 3 — enforce NOT NULL. Safe now that every row has a value.
    op.alter_column(
        "campaigns",
        "owner_user_id",
        existing_type=sa.dialects.postgresql.UUID(as_uuid=True),
        nullable=False,
    )


def downgrade() -> None:
    # Reversible: drop the NOT NULL constraint but leave backfilled
    # ownership in place. Re-running the upgrade is a no-op since
    # everything already has an owner at that point.
    op.alter_column(
        "campaigns",
        "owner_user_id",
        existing_type=sa.dialects.postgresql.UUID(as_uuid=True),
        nullable=True,
    )
