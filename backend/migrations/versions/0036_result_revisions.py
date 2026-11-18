"""Append-only recovered result evidence. Historical cases/reports are unchanged."""

from alembic import op

from autoeval.evaluation.models import ResultArchiveRevision

revision = "0036_result_revisions"
down_revision = "0035_budget_requests"
branch_labels = depends_on = None


def upgrade():
    ResultArchiveRevision.__table__.create(op.get_bind())


def downgrade():
    ResultArchiveRevision.__table__.drop(op.get_bind())
