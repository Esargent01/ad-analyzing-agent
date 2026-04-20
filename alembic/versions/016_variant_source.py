"""Add source column to variants to mark provenance.

Revision ID: 016_variant_source
Revises: 015_variant_media_type
Create Date: 2026-04-20

Records where a variant row came from:

- ``imported`` — seeded during the initial self-serve ``import_campaign``
  flow (i.e. the ad already existed on Meta when the user connected it
  to Kleiber). This is the default for every existing row.
- ``discovered`` — found by the ongoing sync step in ``ad_sync`` on a
  daily/optimization cron tick. The user created an ad in Meta Ads
  Manager directly (bypassing Kleiber), and our diff against
  ``deployments`` caught it. Pulled in so polling and reporting cover
  it going forward.
- ``generated`` — produced by Kleiber's LLM variant generator and
  launched via the deploy step. Not populated yet by the generator
  (follow-up), but reserved so the enum doesn't need a migration later.

Stored as a plain VARCHAR(16) — no Postgres ENUM type. Cheaper to
extend, and the application-layer Pydantic/ORM validation is already
the contract.
"""

import sqlalchemy as sa

from alembic import op

revision = "016_variant_source"
down_revision = "015_variant_media_type"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "variants",
        sa.Column(
            "source",
            sa.String(length=16),
            nullable=False,
            server_default="imported",
        ),
    )


def downgrade() -> None:
    op.drop_column("variants", "source")
