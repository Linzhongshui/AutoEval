"""Persist follow-up execution rounds, requests and shards."""

from alembic import op

from autoeval.evaluation.models import ExecutionRound, ExecutionShard, RoundRequest

revision = "0037_execution_rounds"
down_revision = "0036_result_revisions"
branch_labels = depends_on = None


def upgrade():
    bind = op.get_bind()
    for model in (ExecutionRound, RoundRequest, ExecutionShard):
        model.__table__.create(bind)


def downgrade():
    bind = op.get_bind()
    for model in (ExecutionShard, RoundRequest, ExecutionRound):
        model.__table__.drop(bind)
