"""Add the ``usage_log`` hypertable for per-user cost tracking.

Phase E of the self-serve multi-tenant migration. Every LLM call
(generator / analyst / copywriter) and every Meta API call writes
one row here with its cost — enabling:

- A "This month" tile on each user's dashboard
- Bounded monthly spend visibility per campaign
- Rate-limit + billing attribution downstream (Phase G)

The table is a TimescaleDB hypertable partitioned on
``recorded_at`` so the "usage in the last N days" queries stay
cheap even as row counts grow. The two supporting indexes cover
the per-user and per-campaign read paths.

``ON DELETE SET NULL`` on every FK: deleting a user or campaign
must not erase historical cost records. They stay in the log as
orphans for audit purposes.

Revision ID: 007_usage_log
Revises: 006_campaign_owner
Create Date: 2026-04-09

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "007_usage_log"
down_revision: str | None = "006_campaign_owner"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "usage_log",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            nullable=False,
            server_default=sa.text("uuid_generate_v4()"),
        ),
        sa.Column(
            "user_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "campaign_id",
            UUID(as_uuid=True),
            sa.ForeignKey("campaigns.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "cycle_id",
            UUID(as_uuid=True),
            sa.ForeignKey("test_cycles.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("service", sa.Text(), nullable=False),
        sa.Column("agent", sa.Text(), nullable=True),
        sa.Column("model", sa.Text(), nullable=True),
        sa.Column("input_units", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("output_units", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column(
            "cost_usd",
            sa.Numeric(12, 6),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column("metadata_json", JSONB, nullable=True),
        sa.Column(
            "recorded_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )

    # Hypertables need the partitioning column in the primary key.
    op.execute("ALTER TABLE usage_log ADD PRIMARY KEY (recorded_at, id)")
    op.execute("SELECT create_hypertable('usage_log', 'recorded_at')")

    op.execute("CREATE INDEX idx_usage_log_user ON usage_log (user_id, recorded_at DESC)")
    op.execute("CREATE INDEX idx_usage_log_campaign ON usage_log (campaign_id, recorded_at DESC)")
    op.execute("CREATE INDEX idx_usage_log_service ON usage_log (service, recorded_at DESC)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_usage_log_service")
    op.execute("DROP INDEX IF EXISTS idx_usage_log_campaign")
    op.execute("DROP INDEX IF EXISTS idx_usage_log_user")
    op.drop_table("usage_log")
