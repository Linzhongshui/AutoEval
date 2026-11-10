"""Protect case identity and finalized evidence against accidental mutation."""

from alembic import op

revision = "0011_immutable_case_history"
down_revision = "0010_case_history"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
    CREATE FUNCTION protect_case_execution_history() RETURNS trigger AS $$
    BEGIN
      IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'Case execution history cannot be deleted';
      END IF;
      IF OLD.state <> 'started' THEN
        RAISE EXCEPTION 'Finalized case execution history is immutable';
      END IF;
      IF (NEW.id, NEW.created_at, NEW.run_id, NEW.dataset_key, NEW.sample_id, NEW.attempt_no, NEW.operation_key)
         IS DISTINCT FROM
         (OLD.id, OLD.created_at, OLD.run_id, OLD.dataset_key, OLD.sample_id, OLD.attempt_no, OLD.operation_key) THEN
        RAISE EXCEPTION 'Case execution identity is immutable';
      END IF;
      RETURN NEW;
    END;
    $$ LANGUAGE plpgsql;
    """)
    op.execute("""
    CREATE TRIGGER case_history_immutable BEFORE UPDATE OR DELETE ON case_execution_record
      FOR EACH ROW EXECUTE FUNCTION protect_case_execution_history();
    """)


def downgrade():
    op.execute("DROP TRIGGER case_history_immutable ON case_execution_record")
    op.execute("DROP FUNCTION protect_case_execution_history()")
