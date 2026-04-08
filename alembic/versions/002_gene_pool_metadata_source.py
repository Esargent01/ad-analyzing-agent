"""Add metadata and source columns to gene_pool table.

Revision ID: 002_gene_pool_meta
Revises: 001_initial
Create Date: 2026-04-08

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

# revision identifiers, used by Alembic.
revision: str = "002_gene_pool_meta"
down_revision: Union[str, None] = "001_initial"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("gene_pool", sa.Column("metadata", JSONB, nullable=True))
    op.add_column("gene_pool", sa.Column("source", sa.Text(), nullable=True))

    # Backfill existing entries as 'seed' source
    op.execute("UPDATE gene_pool SET source = 'seed' WHERE source IS NULL")


def downgrade() -> None:
    op.drop_column("gene_pool", "source")
    op.drop_column("gene_pool", "metadata")
