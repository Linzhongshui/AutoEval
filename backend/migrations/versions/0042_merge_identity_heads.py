"""Join identity auth branch with evaluation/report branch heads."""

revision = "0042_merge_identity_heads"
down_revision = ("0037_identity", "0041_report_versions")
branch_labels = depends_on = None


def upgrade():
    pass


def downgrade():
    pass