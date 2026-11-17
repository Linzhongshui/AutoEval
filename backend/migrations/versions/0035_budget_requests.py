"""Persist request reservations; no inferred release after interrupted model calls."""

from alembic import op

from autoeval.billing import BudgetRequest

revision = "0035_budget_requests"
down_revision = "0034_model_billing"
branch_labels = depends_on = None


def upgrade():
    BudgetRequest.__table__.create(op.get_bind())


def downgrade():
    BudgetRequest.__table__.drop(op.get_bind())
