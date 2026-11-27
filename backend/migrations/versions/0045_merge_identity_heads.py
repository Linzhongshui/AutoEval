"""Join identity auth branch with the upstream evaluation/report chain head.

原编号 0042-0044 与上游新迁移冲突，本分支迁移重编号为 0045-0047；
合并节点连接 0037_identity 与上游链头 0044_compilation_display_name。
"""

revision = "0045_merge_identity_heads"
down_revision = ("0037_identity", "0044_compilation_display_name")
branch_labels = depends_on = None


def upgrade():
    pass


def downgrade():
    pass