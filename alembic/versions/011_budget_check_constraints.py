"""Add CHECK constraints for positive daily budgets.

Prevents negative or zero budgets at the database level, regardless of
application-layer bugs. The application validates budget proposals in
``queue_scale_proposal`` and ``_execute_scale``, but a DB-level guard
is a safety net.

Revision ID: 011
Revises: 010
"""

from alembic import op

revision = "011_budget_check_constraints"
down_revision = "010_approval_queue_actions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_check_constraint(
        "ck_campaigns_daily_budget_positive",
        "campaigns",
        "daily_budget > 0",
    )
    op.create_check_constraint(
        "ck_deployments_daily_budget_positive",
        "deployments",
        "daily_budget > 0",
    )


def downgrade() -> None:
    op.drop_constraint("ck_deployments_daily_budget_positive", "deployments")
    op.drop_constraint("ck_campaigns_daily_budget_positive", "campaigns")
