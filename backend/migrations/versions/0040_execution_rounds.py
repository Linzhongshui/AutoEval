"""Persist follow-up execution rounds, requests and shards."""

from alembic import op

from autoeval.evaluation.models import (
    ExecutionRound,
    ExecutionShard,
    ExecutionShardEnvironment,
    RoundRequest,
)

revision = "0040_execution_rounds"
down_revision = "0039_merge_report_and_execution"
branch_labels = depends_on = None


def upgrade():
    bind = op.get_bind()
    for model in (ExecutionRound, RoundRequest, ExecutionShard, ExecutionShardEnvironment):
        model.__table__.create(bind)


def downgrade():
    bind = op.get_bind()
    for model in (ExecutionShardEnvironment, ExecutionShard, RoundRequest, ExecutionRound):
        model.__table__.drop(bind)
