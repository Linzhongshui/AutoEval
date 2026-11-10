"""SQL-backed navigation and frozen context; no execution or generation."""

import hashlib
import os
import uuid

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from autoeval.api import create_app
from autoeval.config import Settings
from autoeval.datasets import canonical_manifest
from autoeval.models import EvaluationRun, RunSnapshot

pytestmark = pytest.mark.skipif(
    not os.environ.get("AE_TEST_DATABASE_URL"), reason="PostgreSQL required"
)


def test_target_context_resolves_current_default_and_configuration_by_exact_id(tmp_path):
    settings = Settings(
        environment="test",
        database_url=os.environ["AE_TEST_DATABASE_URL"],
        secret_store_path=tmp_path,
    )
    prefix = "navigation-" + uuid.uuid4().hex
    with TestClient(create_app(settings)) as client:
        model = client.post(
            "/api/autoeval/v1/models", json={"model_id": prefix, "name": prefix, "version": "v1"}
        ).json()["data"]
        reference = client.post(
            "/api/autoeval/v1/credentials", json={"value": "fixture-never-used-for-generation"}
        ).json()["data"]["credential_ref"]
        target = client.post(
            "/api/autoeval/v1/target-bindings",
            json={
                "model_version_id": model["version_id"],
                "base_url": "https://api.deepseek.com",
                "remote_model": "deepseek-flash",
                "credential_ref": reference,
            },
        ).json()["data"]
        path = f"/api/autoeval/v1/target-bindings?target_id={target['id']}"
        assert client.get(path).json()["data"][0]["default_config_version_id"] is None
        for index in range(2):
            config = client.post(
                "/api/autoeval/v1/test-configs",
                json={
                    "config_key": prefix + str(index),
                    "display_name": prefix,
                    "version_label": "v1",
                    "expected_version": 0,
                    "items": {
                        "GPQA": {
                            "scope": "Lite",
                            "output": 32,
                            "concurrency": 1,
                            "temperature": 0,
                            "top_p": 1,
                        }
                    },
                },
            ).json()["data"]
            response = client.put(
                f"/api/autoeval/v1/models/{model['id']}/default-test-config",
                headers={"If-Match": str(index)},
                json={"config_version_id": config["id"]},
            )
            assert response.status_code == 200
            rows = client.get(path).json()["data"]
            assert len(rows) == 1 and rows[0]["model_key"] == prefix
            assert rows[0]["model_version"] == "v1"
            assert rows[0]["default_config_version_id"] == config["id"]
            assert "credential_ref" not in rows[0]
            exact = client.get(f"/api/autoeval/v1/test-configs?config_id={config['id']}").json()[
                "data"
            ]
            assert len(exact) == 1 and exact[0]["id"] == config["id"]
        assert (
            client.get(f"/api/autoeval/v1/target-bindings?target_id={uuid.uuid4()}").json()["data"]
            == []
        )
        assert client.get("/api/autoeval/v1/test-configs?config_id=bad").status_code == 422


async def test_run_pages_and_direct_detail_use_frozen_context_without_private_fields():
    settings = Settings(
        environment="test",
        evaluation_origin="simulation",
        database_url=os.environ["AE_TEST_DATABASE_URL"],
    )
    engine = create_async_engine(settings.database_url.get_secret_value())
    async with engine.connect() as connection:
        transaction = await connection.begin()
        sessions = async_sessionmaker(
            connection, expire_on_commit=False, join_transaction_mode="create_savepoint"
        )
        try:
            app = create_app(settings)
            app.state.settings, app.state.sessions = settings, sessions
            ids = []
            async with sessions() as session, session.begin():
                for _ in range(21):
                    run = EvaluationRun(
                        trigger_scope="local-operator:evaluation",
                        idempotency_key=uuid.uuid4().hex,
                        request_hash="a" * 64,
                        run_mode="exploration",
                        created_by="navigation-test",
                        state="completed",
                    )
                    session.add(run)
                    await session.flush()
                    frozen = {
                        "execution_origin": "simulation",
                        "remote_model": "fixture-model",
                        "resource_kind": "customer_ssh",
                        "parameters": {"output": 32},
                        "config_version_id": str(uuid.uuid4()),
                        "samples": [{"sample_id": "fixture-1"}],
                        "private_extension": "fixture-private",
                    }
                    session.add(
                        RunSnapshot(
                            run_id=run.id,
                            schema_version="gpqa-run.v1",
                            canonical_body=frozen,
                            sha256=hashlib.sha256(canonical_manifest(frozen)).hexdigest(),
                        )
                    )
                    ids.append(str(run.id))
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://test"
            ) as api:
                page = (await api.get("/api/autoeval/v1/runs?limit=20")).json()
                assert page["next_offset"] == 20
                second = (await api.get("/api/autoeval/v1/runs?limit=20&offset=20")).json()
                first_ids = {row["id"] for row in page["data"]}
                second_ids = {row["id"] for row in second["data"]}
                assert not first_ids & second_ids
                assert set(ids).issubset(first_ids | second_ids)
                response = await api.get("/api/autoeval/v1/runs/" + ids[0])
                body = response.json()["data"]
                assert body["snapshot"]["parameters"] == {"output": 32}
                assert body["snapshot"]["sample_count"] == 1
                assert body["snapshot"]["resource_kind"] == "customer_ssh"
                assert "fixture-private" not in response.text
                assert (
                    await api.get("/api/autoeval/v1/runs/" + str(uuid.uuid4()))
                ).status_code == 404
        finally:
            await transaction.rollback()
    await engine.dispose()
