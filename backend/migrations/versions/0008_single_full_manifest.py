"""One full sample universe per immutable dataset version."""

import sqlalchemy as sa
from alembic import op

revision = "0008_single_full_manifest"
down_revision = "0007_dataset_manifests"
branch_labels = None
depends_on = None


def upgrade():
    op.create_index(
        "uq_dataset_full_manifest",
        "dataset_manifest",
        ["dataset_version_id"],
        unique=True,
        postgresql_where=sa.text("scope = 'full'"),
    )


def downgrade():
    op.drop_index("uq_dataset_full_manifest", table_name="dataset_manifest")
