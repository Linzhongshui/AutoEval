"""Platform configuration key-value store for admin-managed runtime settings."""

from alembic import op

from autoeval.infrastructure.platform_config import PlatformConfig

revision = "0043_platform_config"
down_revision = "0042_merge_identity_heads"
branch_labels = depends_on = None


def upgrade():
    PlatformConfig.__table__.create(op.get_bind())


def downgrade():
    PlatformConfig.__table__.drop(op.get_bind())
