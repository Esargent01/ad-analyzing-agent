"""Add campaign objective + leads / post_engagements metric columns.

Revision ID: 017_campaign_objective
Revises: 016_variant_source
Create Date: 2026-04-20

Two data-model extensions that together enable objective-aware reports:

1. ``campaigns.objective`` — one-of the six Meta ODAX values plus a
   sentinel ``OUTCOME_UNKNOWN`` for anything the adapter couldn't map.
   Default is ``OUTCOME_SALES`` so existing rows light up with the
   same behaviour we ship today; the one-shot backfill CLI
   (``scripts/backfill_campaign_objective.py``) fills real values by
   re-reading Meta for each imported campaign, and the cron loop
   opportunistically re-reads on every cycle. Stored as a plain
   ``VARCHAR(32)`` + CHECK constraint rather than a PG ``enum`` —
   cheaper to extend if Meta introduces a new objective and avoids
   the ``ALTER TYPE`` dance.

2. ``metrics.leads`` and ``metrics.post_engagements`` — two new
   integer columns on the hypertable so the Leads and Engagement
   objectives can aggregate their headline numbers SQL-side in the
   reports pipeline, same way the existing extended funnel columns
   (``link_clicks`` / ``landing_page_views`` / ``purchases`` / ...)
   already do. Default 0, NOT NULL; every existing row lights up
   with zeroes, matching "no lead / engagement action rows present"
   which is the correct representation for legacy polls.

Downgrade drops all three columns. No FKs, no indexes, no data loss
beyond the new columns themselves.
"""

import sqlalchemy as sa

from alembic import op

revision = "017_campaign_objective"
down_revision = "016_variant_source"
branch_labels = None
depends_on = None


_ALLOWED_OBJECTIVES = (
    "OUTCOME_SALES",
    "OUTCOME_LEADS",
    "OUTCOME_ENGAGEMENT",
    "OUTCOME_TRAFFIC",
    "OUTCOME_AWARENESS",
    "OUTCOME_APP_PROMOTION",
    "OUTCOME_UNKNOWN",
)


def upgrade() -> None:
    op.add_column(
        "campaigns",
        sa.Column(
            "objective",
            sa.String(length=32),
            nullable=False,
            server_default="OUTCOME_SALES",
        ),
    )
    # Lock the enum domain to the seven canonical values. Using a
    # CHECK constraint (not a PG enum) because Meta's objective
    # taxonomy has changed before (legacy → ODAX in 2024) and will
    # likely change again; dropping + re-adding a CHECK is cheap,
    # ``ALTER TYPE`` is not.
    allowed_sql = ", ".join(f"'{v}'" for v in _ALLOWED_OBJECTIVES)
    op.execute(
        f"ALTER TABLE campaigns ADD CONSTRAINT ck_campaigns_objective "
        f"CHECK (objective IN ({allowed_sql}))"
    )

    op.add_column(
        "metrics",
        sa.Column(
            "leads",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )
    op.add_column(
        "metrics",
        sa.Column(
            "post_engagements",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )


def downgrade() -> None:
    op.drop_column("metrics", "post_engagements")
    op.drop_column("metrics", "leads")
    op.execute("ALTER TABLE campaigns DROP CONSTRAINT IF EXISTS ck_campaigns_objective")
    op.drop_column("campaigns", "objective")
