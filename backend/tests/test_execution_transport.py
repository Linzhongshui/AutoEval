import json
import os
import uuid
from types import SimpleNamespace

import pytest
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.exc import DBAPIError

from autoeval.case_history import AttemptEvidence
from autoeval.config import get_settings
from autoeval.db import create_database
from autoeval.execution_transport import frozen_ssh_resource
from autoeval.models import EvaluationRun, RunEvent
from autoeval.resources import ResourceProvider
from autoeval.run_activities import record_unresolved
from autoeval.ssh_resources import SSHResourceBinding


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
        native_bridge_sha256="a" * 64,
        native_lock_sha256="b" * 64,
        native_tool_revision="c" * 40,
        credential_ref="must-not-enter-snapshot",
    )
    frozen = frozen_ssh_resource(row, SimpleNamespace(aisbench_lock_path=lock))
    assert frozen["owner_id"] == str(row.id)
    assert len(frozen["bridge_sha256"]) == len(frozen["lock_sha256"]) == 64
    assert "must-not-enter-snapshot" not in json.dumps(frozen)
    assert "credential_ref" not in frozen
    assert frozen["bridge_sha256"] == "a" * 64
    assert frozen["lock_sha256"] == "b" * 64
    # Missing/new local artifacts cannot invalidate a previously approved binding.
    lock.unlink()
    assert frozen_ssh_resource(row, None) == frozen


def test_ssh_native_tool_root_is_required_before_freezing():
    with pytest.raises(ValueError, match="tool root"):
        frozen_ssh_resource(SimpleNamespace(native_tool_root=None), None)


def test_unpinned_legacy_resource_is_not_silently_approved_by_local_code():
    with pytest.raises(ValueError, match="not pinned"):
        frozen_ssh_resource(
            SimpleNamespace(
                native_tool_root="/opt/tools",
                native_bridge_sha256=None,
                native_lock_sha256=None,
                native_tool_revision=None,
            ),
            None,
        )


@pytest.mark.skipif(not os.environ.get("AE_INFRA_TEST"), reason="PostgreSQL required")
async def test_ssh_tool_pins_and_root_are_immutable_in_postgres():
    engine, sessions = create_database(get_settings())
    try:
        async with sessions() as session:
            transaction = await session.begin()
            try:
                provider = ResourceProvider(
                    name="pin-test-" + uuid.uuid4().hex, kind="customer_ssh"
                )
                session.add(provider)
                await session.flush()
                row = SSHResourceBinding(
                    provider_id=provider.id,
                    binding_key=uuid.uuid4().hex,
                    version=1,
                    host="127.0.0.1",
                    port=22,
                    username="fixture",
                    fingerprint="SHA256:" + "A" * 43,
                    workdir="/work",
                    auth_kind="password",
                    credential_ref="0" * 32,
                    native_tool_root="/opt/approved-v1",
                    native_bridge_sha256="a" * 64,
                    native_lock_sha256="b" * 64,
                    native_tool_revision="c" * 40,
                )
                session.add(row)
                await session.flush()
                for field, value in (
                    ("native_tool_root", "/opt/other"),
                    ("native_bridge_sha256", "d" * 64),
                    ("native_lock_sha256", "e" * 64),
                    ("native_tool_revision", "f" * 40),
                ):
                    with pytest.raises(DBAPIError, match="immutable"):
                        async with session.begin_nested():
                            from sqlalchemy import update

                            await session.execute(
                                update(SSHResourceBinding)
                                .where(SSHResourceBinding.id == row.id)
                                .values(**{field: value})
                            )
                await session.refresh(row)
                assert (
                    row.native_tool_root == "/opt/approved-v1"
                    and row.native_bridge_sha256 == "a" * 64
                )
            finally:
                await transaction.rollback()
    finally:
        await engine.dispose()


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
