import json
import os
import uuid
from types import SimpleNamespace

import pytest
from pydantic import ValidationError
from sqlalchemy import select

from autoeval.case_history import AttemptEvidence
from autoeval.config import get_settings
from autoeval.db import create_database
from autoeval.execution_transport import frozen_ssh_resource
from autoeval.models import EvaluationRun, RunEvent
from autoeval.run_activities import record_unresolved


def test_frozen_ssh_metadata_never_includes_credential_reference(tmp_path):
    lock = tmp_path / "lock.json"
    lock.write_text("{}")
    row = SimpleNamespace(
        id=uuid.uuid4(),
        host="127.0.0.1",
        port=2222,
        username="autoeval",
        fingerprint="SHA256:" + "A" * 43,
        workdir="/work",
        auth_kind="private_key",
        native_tool_root="/opt/tools",
        credential_ref="must-not-enter-snapshot",
    )
    frozen = frozen_ssh_resource(row, SimpleNamespace(aisbench_lock_path=lock))
    assert frozen["owner_id"] == str(row.id)
    assert len(frozen["bridge_sha256"]) == len(frozen["lock_sha256"]) == 64
    assert "must-not-enter-snapshot" not in json.dumps(frozen)
    assert "credential_ref" not in frozen


def test_ssh_native_tool_root_is_required_before_freezing():
    with pytest.raises(ValueError, match="tool root"):
        frozen_ssh_resource(SimpleNamespace(native_tool_root=None), None)


def test_attempt_usage_is_separate_from_output_validity_and_closed_to_secret_fields():
    evidence = AttemptEvidence(
        state="succeeded",
        prompt="fixture",
        response="",
        finish_reason="length",
        usage={"input_tokens": 5, "output_tokens": 0},
    )
    assert evidence.state == "succeeded" and evidence.response == ""
    assert evidence.model_dump()["usage"] == {"input_tokens": 5, "output_tokens": 0}
    with pytest.raises(ValidationError):
        AttemptEvidence(
            state="succeeded",
            prompt="fixture",
            response="A",
            usage={"input_tokens": -1, "output_tokens": 1},
        )
    with pytest.raises(ValidationError):
        AttemptEvidence(
            state="succeeded",
            prompt="fixture",
            response="A",
            usage={"input_tokens": 1, "output_tokens": 1, "api_key": "not-allowed"},
        )


@pytest.mark.skipif(not os.environ.get("AE_INFRA_TEST"), reason="Live PostgreSQL required")
async def test_stale_activity_cannot_mark_completed_run_unresolved():
    engine, sessions = create_database(get_settings())
    try:
        async with sessions() as session, session.begin():
            run = EvaluationRun(
                trigger_scope="terminal-guard-fixture",
                idempotency_key=uuid.uuid4().hex,
                request_hash="a" * 64,
                run_mode="exploration",
                created_by="integration-test",
                state="completed",
            )
            session.add(run)
            await session.flush()
            run_id = run.id
        await record_unresolved(sessions, run_id)
        async with sessions() as session:
            row = await session.get(EvaluationRun, run_id)
            assert row.state == "completed" and row.projection_version == 1
            assert (
                await session.scalar(select(RunEvent.id).where(RunEvent.run_id == run_id)) is None
            )
    finally:
        await engine.dispose()
