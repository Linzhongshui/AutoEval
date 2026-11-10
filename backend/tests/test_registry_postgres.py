import os
import uuid

import pytest
from fastapi.testclient import TestClient

from autoeval.api import create_app
from autoeval.config import Settings


@pytest.mark.skipif(not os.environ.get("AE_TEST_DATABASE_URL"), reason="Real PostgreSQL required")
def test_model_registration_and_optimistic_default_pointer():
    app = create_app(Settings(environment="test", database_url=os.environ["AE_TEST_DATABASE_URL"]))
    key = uuid.uuid4().hex
    with TestClient(app) as client:
        model = client.post(
            "/api/autoeval/v1/models",
            json={"model_id": key, "name": "integration", "version": "v1"},
        )
        assert model.status_code == 201, model.text
        model_id = model.json()["data"]["id"]
        config = client.post(
            "/api/autoeval/v1/test-configs",
            json={
                "config_key": key,
                "display_name": "test",
                "version_label": "one",
                "expected_version": 0,
                "items": {
                    "GPQA": {
                        "output": 100,
                        "concurrency": 1,
                        "temperature": 0.5,
                        "top_p": 1,
                        "scope": "全量",
                    }
                },
            },
        )
        config_id = config.json()["data"]["id"]
        path = f"/api/autoeval/v1/models/{model_id}/default-test-config"
        assert (
            client.put(
                path, json={"config_version_id": config_id}, headers={"If-Match": "0"}
            ).status_code
            == 200
        )
        assert (
            client.put(
                path, json={"config_version_id": config_id}, headers={"If-Match": "0"}
            ).status_code
            == 412
        )
        assert (
            client.put(
                path, json={"config_version_id": str(uuid.uuid4())}, headers={"If-Match": "1"}
            ).status_code
            == 404
        )
        rows = client.get("/api/autoeval/v1/models").json()["data"]
        stored = next(r for r in rows if r["id"] == model_id)
        assert stored["default_config_version_id"] == config_id
        assert stored["connection_state"] == "not_configured"
