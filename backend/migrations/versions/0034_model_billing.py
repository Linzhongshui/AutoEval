"""Add official price versions and independent CNY budgets; no historical spend inferred."""
from alembic import op

from autoeval.billing import BudgetAccount, ModelPrice, TargetBilling

revision = '0034_model_billing'
down_revision = '0033_langfuse_content_mode'
branch_labels = depends_on = None


def upgrade():
    for table in (ModelPrice.__table__, BudgetAccount.__table__, TargetBilling.__table__):
        table.create(op.get_bind())


def downgrade():
    for table in (TargetBilling.__table__, BudgetAccount.__table__, ModelPrice.__table__):
        table.drop(op.get_bind())
