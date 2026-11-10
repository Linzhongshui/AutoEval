"""Pin resource tool artifacts without treating a backend upgrade as approval."""

import sqlalchemy as sa
from alembic import op

revision = "0021_ssh_artifact_pins"
down_revision = "0020_execution_cleanup"
branch_labels = depends_on = None


def upgrade():
    for name in ("native_bridge_sha256", "native_lock_sha256", "native_tool_revision"):
        op.add_column("ssh_resource_binding", sa.Column(name, sa.String(64)))
    # Existing resources are pinned only from unambiguous prior frozen execution
    # evidence for the SAME owner and tool root. Others stay explicitly unpinned.
    op.execute("""
        WITH candidates AS (
            SELECT canonical_body #>> '{ssh,owner_id}' AS owner_id,
                   canonical_body #>> '{ssh,tool_root}' AS tool_root,
                   canonical_body #>> '{ssh,bridge_sha256}' AS bridge,
                   canonical_body #>> '{ssh,lock_sha256}' AS lock_hash,
                   canonical_body #>> '{tool,revision}' AS revision
            FROM run_snapshot
            WHERE canonical_body->>'resource_kind' = 'customer_ssh'
        ), pins AS (
            SELECT owner_id, tool_root, min(bridge) AS bridge,
                   min(lock_hash) AS lock_hash, min(revision) AS revision
            FROM candidates
            GROUP BY owner_id, tool_root
            HAVING count(DISTINCT (bridge, lock_hash, revision)) = 1
               AND bool_and(bridge ~ '^[0-9a-f]{64}$' AND lock_hash ~ '^[0-9a-f]{64}$'
                            AND revision ~ '^([0-9a-f]{40}|[0-9a-f]{64})$')
        )
        UPDATE ssh_resource_binding AS resource
        SET native_bridge_sha256 = pins.bridge,
            native_lock_sha256 = pins.lock_hash,
            native_tool_revision = pins.revision
        FROM pins WHERE resource.id::text = pins.owner_id
                   AND resource.native_tool_root = pins.tool_root
    """)
    op.create_check_constraint(
        "ck_ssh_native_pins",
        "ssh_resource_binding",
        "(native_bridge_sha256 IS NULL AND native_lock_sha256 IS NULL AND native_tool_revision IS NULL) OR "
        "(native_tool_root IS NOT NULL AND native_bridge_sha256 IS NOT NULL AND native_lock_sha256 IS NOT NULL AND native_tool_revision IS NOT NULL "
        "AND native_bridge_sha256 ~ '^[0-9a-f]{64}$' AND native_lock_sha256 ~ '^[0-9a-f]{64}$' AND native_tool_revision ~ '^([0-9a-f]{40}|[0-9a-f]{64})$')",
    )
    op.execute("""
        CREATE FUNCTION protect_ssh_artifact_pins() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF ROW(NEW.native_tool_root, NEW.native_bridge_sha256, NEW.native_lock_sha256, NEW.native_tool_revision)
               IS DISTINCT FROM ROW(OLD.native_tool_root, OLD.native_bridge_sha256, OLD.native_lock_sha256, OLD.native_tool_revision) THEN
                RAISE EXCEPTION 'SSH tool artifacts are immutable; register a new resource version';
            END IF;
            RETURN NEW;
        END $$;
    """)
    op.execute(
        "CREATE TRIGGER ssh_artifact_pins_immutable BEFORE UPDATE ON ssh_resource_binding FOR EACH ROW EXECUTE FUNCTION protect_ssh_artifact_pins()"
    )


def downgrade():
    op.execute("DROP TRIGGER ssh_artifact_pins_immutable ON ssh_resource_binding")
    op.execute("DROP FUNCTION protect_ssh_artifact_pins()")
    op.drop_constraint("ck_ssh_native_pins", "ssh_resource_binding")
    for name in ("native_tool_revision", "native_lock_sha256", "native_bridge_sha256"):
        op.drop_column("ssh_resource_binding", name)
