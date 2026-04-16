"""Flag one campaign as the public showcase + log daily tweets.

The auto-tweet job needs two things from the DB:

1. A way to identify *which* campaign is the public Kleiber showcase
   (we only tweet about Kleiber's own campaign; customer campaigns
   stay private). ``campaigns.is_public_showcase`` is a boolean flag
   with a partial unique index so at most one campaign can be
   flagged at any time.

2. An idempotency log so the cron doesn't double-post if it reruns.
   ``daily_tweet_log`` records one row per (campaign, date).

Revision ID: 014_campaign_public_showcase
Revises: 013
Create Date: 2026-04-16
"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

from alembic import op

revision = "014_campaign_public_showcase"
down_revision = "013_beta_signups"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "campaigns",
        sa.Column(
            "is_public_showcase",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    # Partial unique index — only enforces uniqueness on rows where
    # the flag is TRUE. Any number of rows can be FALSE.
    op.execute(
        "CREATE UNIQUE INDEX ix_campaigns_public_showcase "
        "ON campaigns (is_public_showcase) "
        "WHERE is_public_showcase = true"
    )

    op.create_table(
        "daily_tweet_log",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            server_default=sa.text("uuid_generate_v4()"),
            primary_key=True,
        ),
        sa.Column(
            "campaign_id",
            UUID(as_uuid=True),
            sa.ForeignKey("campaigns.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("tweet_date", sa.Date(), nullable=False),
        # Nullable so we can record dry-run / dev-mode drafts that
        # never actually hit the X API.
        sa.Column("tweet_id", sa.Text(), nullable=True),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column(
            "posted_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint(
            "campaign_id",
            "tweet_date",
            name="uq_daily_tweet_log_campaign_date",
        ),
    )


def downgrade() -> None:
    op.drop_table("daily_tweet_log")
    op.execute("DROP INDEX IF EXISTS ix_campaigns_public_showcase")
    op.drop_column("campaigns", "is_public_showcase")
