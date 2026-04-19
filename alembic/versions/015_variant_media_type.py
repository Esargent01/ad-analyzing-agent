"""Add media_type to variants for image/video/mixed distinction.

Revision ID: 015_variant_media_type
Revises: 013_beta_signups
Create Date: 2026-04-19

Adds a small VARCHAR column to ``variants`` carrying the creative's
media type as reported by Meta (``VIDEO`` / ``PHOTO`` / ``SHARE`` /
``MULTI_SHARE``), mapped into our internal taxonomy
(``"video"`` / ``"image"`` / ``"mixed"`` / ``"unknown"``).

Default is ``'unknown'`` NOT NULL — every existing row lights up
safely; the reporting layer treats unknown identically to
video/mixed (full funnel), so pre-existing behavior is preserved
until the column is filled by a fresh import or the
``backfill-media-type`` CLI.

Downgrade drops the column outright; there are no dependent FKs or
indexes.
"""

import sqlalchemy as sa

from alembic import op

revision = "015_variant_media_type"
down_revision = "013_beta_signups"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "variants",
        sa.Column(
            "media_type",
            sa.String(length=16),
            nullable=False,
            server_default="unknown",
        ),
    )


def downgrade() -> None:
    op.drop_column("variants", "media_type")
