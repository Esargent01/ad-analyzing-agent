"""Create data_deletion_requests table for Meta compliance.

Revision ID: 012
Revises: 011
Create Date: 2026-04-13
"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

from alembic import op

revision = "012"
down_revision = "011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "data_deletion_requests",
        sa.Column(
            "id", UUID(as_uuid=True), server_default=sa.text("uuid_generate_v4()"), primary_key=True
        ),
        sa.Column("confirmation_code", sa.Text(), nullable=False, unique=True),
        sa.Column("meta_user_id", sa.Text(), nullable=False),
        sa.Column(
            "user_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("status", sa.Text(), nullable=False, server_default="completed"),
        sa.Column(
            "requested_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index(
        "ix_data_deletion_requests_confirmation_code",
        "data_deletion_requests",
        ["confirmation_code"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_data_deletion_requests_confirmation_code", table_name="data_deletion_requests"
    )
    op.drop_table("data_deletion_requests")
