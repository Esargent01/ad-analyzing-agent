"""Add owner_user_id to campaigns.

Nullable on purpose: legacy campaigns don't have an owner until
Phase F backfills them. The per-user MetaAdapter factory treats
``NULL`` as "fall back to the global token" — that fallback is
removed in Phase F after the backfill runs.

``ON DELETE SET NULL`` is intentional. Deleting a user should
orphan their campaigns (requiring manual intervention to reassign
or retire them) rather than cascade-deleting potentially valuable
historical data. See red flag #6 in the plan.

Part of Phase C of the self-serve multi-tenant migration.

Revision ID: 006_campaign_owner
Revises: 005_user_meta_connections
Create Date: 2026-04-09

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID


# revision identifiers, used by Alembic.
revision: str = "006_campaign_owner"
down_revision: Union[str, None] = "005_user_meta_connections"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "campaigns",
        sa.Column(
            "owner_user_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    # Partial index so we only pay for rows that actually have an
    # owner — until Phase F most rows will be NULL and excluded.
    op.create_index(
        "idx_campaigns_owner",
        "campaigns",
        ["owner_user_id"],
        postgresql_where=sa.text("owner_user_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("idx_campaigns_owner", table_name="campaigns")
    op.drop_column("campaigns", "owner_user_id")
