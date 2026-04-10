"""Per-user Meta OAuth connection storage.

Each row holds an encrypted Meta access token for exactly one app user.
The ``encrypted_access_token`` column is the output of
``src.dashboard.crypto.encrypt_token`` — the DB never sees plaintext.

A single unique row per user_id is intentional: Phase B only supports
one Meta connection per user. If a user re-OAuths, the upsert
overwrites the existing row with the new token.

Part of Phase B of the self-serve multi-tenant migration.

Revision ID: 005_user_meta_connections
Revises: 004_magic_links_consumed
Create Date: 2026-04-09

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import ARRAY, UUID

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "005_user_meta_connections"
down_revision: str | None = "004_magic_links_consumed"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "user_meta_connections",
        sa.Column(
            "user_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("meta_user_id", sa.Text(), nullable=False),
        sa.Column("encrypted_access_token", sa.Text(), nullable=False),
        sa.Column("token_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("scopes", ARRAY(sa.Text()), nullable=True),
        sa.Column(
            "connected_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("last_refreshed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "idx_user_meta_connections_meta_user_id",
        "user_meta_connections",
        ["meta_user_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "idx_user_meta_connections_meta_user_id",
        table_name="user_meta_connections",
    )
    op.drop_table("user_meta_connections")
