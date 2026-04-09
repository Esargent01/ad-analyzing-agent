"""Auth tables: users and user_campaigns.

Adds dashboard user accounts (provisioned manually via the ``grant-access``
CLI) and a join table scoping each user to specific campaigns. All dashboard
API endpoints that accept a session cookie consult ``user_campaigns`` to
decide whether the caller may see a given campaign.

Revision ID: 003_auth_tables
Revises: 002_gene_pool_meta
Create Date: 2026-04-09

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

# revision identifiers, used by Alembic.
revision: str = "003_auth_tables"
down_revision: Union[str, None] = "002_gene_pool_meta"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # users
    # ------------------------------------------------------------------
    op.create_table(
        "users",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("uuid_generate_v4()"),
        ),
        sa.Column("email", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.UniqueConstraint("email", name="uq_users_email"),
    )
    op.create_index("idx_users_email", "users", ["email"])

    # ------------------------------------------------------------------
    # user_campaigns
    # ------------------------------------------------------------------
    op.create_table(
        "user_campaigns",
        sa.Column(
            "user_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "campaign_id",
            UUID(as_uuid=True),
            sa.ForeignKey("campaigns.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "granted_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("idx_user_campaigns_user", "user_campaigns", ["user_id"])
    op.create_index(
        "idx_user_campaigns_campaign", "user_campaigns", ["campaign_id"]
    )


def downgrade() -> None:
    op.drop_index("idx_user_campaigns_campaign", table_name="user_campaigns")
    op.drop_index("idx_user_campaigns_user", table_name="user_campaigns")
    op.drop_table("user_campaigns")

    op.drop_index("idx_users_email", table_name="users")
    op.drop_table("users")
