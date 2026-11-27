"""Record the deployment source of model inference services."""
import sqlalchemy as sa
from alembic import op

revision = "0042_target_service_kind"
down_revision = "0041_report_versions"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("target_binding_version", sa.Column("service_kind", sa.String(16), nullable=True))


def downgrade():
    op.drop_column("target_binding_version", "service_kind")
