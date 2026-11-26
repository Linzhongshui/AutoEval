"""Real database/storage tests with remote calls intercepted; no model calls."""

import os
import uuid
from contextlib import asynccontextmanager
from hashlib import sha256
from unittest.mock import AsyncMock

import httpx
import pytest
from sqlalchemy import select

from autoeval.catalog.models import TestConfigVersion as ConfigVersion
from autoeval.entrypoints.api import create_app
from autoeval.evaluation.evaluations import EvaluationReport
from autoeval.evaluation.fixture_pipeline import execute_unified_fixture
from autoeval.infrastructure.config import get_settings
from autoeval.infrastructure.models import EvaluationRun, RunSnapshot
from autoeval.reporting.models import UnifiedArtifact
from autoeval.reporting.unified_outputs import read_raw_output


@pytest.mark.asyncio
@pytest.mark.skipif(
    os.getenv("AE_INFRA_TEST") != "1", reason="Requires PostgreSQL, S3 and protected fixture config"
)
async def test_submission_idempotency_failure_and_cancel_without_model(monkeypatch):
    app = create_app(get_settings())
    async with app.router.lifespan_context(app):
        async with app.state.sessions() as session:
            config = await session.scalar(
                select(ConfigVersion).where(ConfigVersion.kind == "standard").limit(1)
            )
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            # Outbox remains pending for the normal dispatcher; cancellation is committed immediately.
            key = "TEST-fixture-cancel-" + uuid.uuid4().hex
            response = await client.post(
                "/api/autoeval/v1/diagnostics/unified-fixture",
                json={"config_version_id": str(config.id)},
                headers={"Idempotency-Key": key},
            )
            assert response.status_code == 202, response.text
            run_id = response.json()["data"]["run_id"]
            duplicate = await client.post(
                "/api/autoeval/v1/diagnostics/unified-fixture",
                json={"config_version_id": str(config.id)},
                headers={"Idempotency-Key": key},
            )
            assert duplicate.json()["data"]["run_id"] == run_id
            cancelled = await client.post(f"/api/autoeval/v1/runs/{run_id}/cancel")
            assert cancelled.status_code == 202, cancelled.text
            monkeypatch.setattr(
                "autoeval.evaluation.fixture_pipeline.fetch_remote",
                lambda *args: pytest.fail("Cancelled run must not connect"),
            )
            result = await execute_unified_fixture(run_id)
            assert result["state"] == "cancelled"
            async with app.state.sessions() as session:
                assert (await session.get(EvaluationRun, uuid.UUID(run_id))).state == "cancelled"


@pytest.mark.asyncio
@pytest.mark.skipif(
    os.getenv("AE_INFRA_TEST") != "1", reason="Requires existing fixture evidence and PostgreSQL/S3"
)
async def test_upload_failure_then_retry_without_remote_reexecution(monkeypatch):
    from autoeval.evaluation import fixture_pipeline as module

    settings = get_settings()
    app = create_app(settings)
    identifier = uuid.uuid4()
    async with app.router.lifespan_context(app):
        async with app.state.sessions() as session, session.begin():
            source = await session.scalar(
                select(UnifiedArtifact)
                .where(UnifiedArtifact.collection_key == "fixture-v1")
                .order_by(UnifiedArtifact.created_at.desc())
                .limit(1)
            )
            snapshot = await session.scalar(
                select(RunSnapshot).where(RunSnapshot.run_id == source.run_id)
            )
            raw = read_raw_output(
                settings, {"object_key": source.object_key, "sha256": source.sha256}
            )
            session.add(
                EvaluationRun(
                    id=identifier,
                    trigger_scope="local-operator:unified-fixture",
                    idempotency_key="TEST-recovery-" + str(identifier),
                    request_hash="a" * 64,
                    run_mode="exploration",
                    created_by="TEST-fixture-recovery",
                )
            )
            await session.flush()
            session.add(
                RunSnapshot(
                    run_id=identifier,
                    schema_version="fixture.v1",
                    canonical_body=snapshot.canonical_body,
                    sha256=snapshot.sha256,
                )
            )
        monkeypatch.setattr(module, "fetch_remote", lambda *args: raw)
        monkeypatch.setattr(module, "fetch_local", AsyncMock(return_value=raw))
        original = module.write_manifest

        def fail_upload(*args):
            raise OSError("Injected storage failure")

        monkeypatch.setattr(module, "write_manifest", fail_upload)
        with pytest.raises(OSError):
            await execute_unified_fixture(str(identifier))
        async with app.state.sessions() as session:
            assert (await session.get(EvaluationRun, identifier)).state == "failed"
            assert not await session.scalar(
                select(EvaluationReport).where(EvaluationReport.run_id == identifier)
            )
        monkeypatch.setattr(module, "write_manifest", original)
        result = await execute_unified_fixture(str(identifier))
        assert result["execution_origin"] == "simulation"
        again = await execute_unified_fixture(str(identifier))
        assert result["report_id"] == again["report_id"]


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["complete", "truncated", "wrong_digest", "wrong_storage"])
async def test_local_fixture_requires_complete_pinned_output(mode, monkeypatch):
    from autoeval.evaluation.fixture_pipeline import fetch_local
    from autoeval.planning import debug_storage, planning_transport

    text = '{"origin":"simulation"}'
    binding = {"container": "fixture", "mount": "mount-digest", "store": str(uuid.uuid4())}
    job = str(uuid.uuid4())
    frozen = {
        "resource": {"debug_storage": binding},
        "fixture_source_job": job,
        "fixture_environment": {
            "source_sha256": "0" * 64
            if mode == "wrong_digest"
            else sha256(text.encode()).hexdigest()
        },
    }

    @asynccontextmanager
    async def sessions():
        yield None

    adapter = object()
    monkeypatch.setattr(planning_transport, "transport", AsyncMock(return_value=adapter))

    def browse(actual, pinned, query):
        assert actual is adapter and pinned == binding
        assert query == {"job": job, "path": "output/unified_result.json"}
        if mode == "wrong_storage":
            return {"state": mode}
        size = len(text.encode())
        return {
            "state": "text",
            "content": text,
            "start": 0,
            "end": size,
            "size": size + (mode == "truncated"),
        }

    monkeypatch.setattr(debug_storage, "browse_store", browse)
    if mode == "complete":
        assert await fetch_local(sessions, None, frozen) == text.encode()
    else:
        with pytest.raises(ValueError):
            await fetch_local(sessions, None, frozen)
