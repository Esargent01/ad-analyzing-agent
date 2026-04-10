"""Magic-link single-use enforcement table.

Adds a ``magic_links_consumed`` ledger keyed by the SHA-256 hash of the
raw magic-link token. ``api_auth_verify`` does an ``INSERT ... ON CONFLICT
DO NOTHING`` against this table before issuing a session cookie — the first
verify wins, every subsequent replay of the same link 400s. We store only
the hash (not the token) so a leaked DB dump can't be replayed.

Part of Phase A of the self-serve multi-tenant migration.

Revision ID: 004_magic_links_consumed
Revises: 003_auth_tables
Create Date: 2026-04-09

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "004_magic_links_consumed"
down_revision: str | None = "003_auth_tables"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "magic_links_consumed",
        sa.Column("token_hash", sa.Text(), primary_key=True),
        sa.Column(
            "consumed_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index(
        "idx_magic_links_consumed_at",
        "magic_links_consumed",
        ["consumed_at"],
    )


def downgrade() -> None:
    op.drop_index("idx_magic_links_consumed_at", table_name="magic_links_consumed")
    op.drop_table("magic_links_consumed")
