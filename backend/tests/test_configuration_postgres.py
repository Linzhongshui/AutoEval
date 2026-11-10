"""Opt-in real PostgreSQL contract test; no SQLite or mocked persistence."""

import os
import uuid

import pytest
from fastapi.testclient import TestClient

from autoeval.api import create_app
from autoeval.config import Settings


@pytest.mark.skipif(
    not os.environ.get("AE_TEST_DATABASE_URL"), reason="Real PostgreSQL URL required"
)
def test_configuration_roundtrip_and_version_conflict():
    settings = Settings(environment="test", database_url=os.environ["AE_TEST_DATABASE_URL"])
    key = "integration-" + uuid.uuid4().hex
    payload = {
        "config_key": key,
        "display_name": "真实数据库测试",
        "version_label": "first",
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
    }
    with TestClient(create_app(settings)) as client:
        first = client.post("/api/autoeval/v1/test-configs", json=payload)
        assert first.status_code == 201, first.text
        assert client.post("/api/autoeval/v1/test-configs", json=payload).status_code == 409
        second = {
            **payload,
            "version_label": "second",
            "expected_version": 1,
            "items": {**payload["items"], "MMMU-Pro": payload["items"]["GPQA"]},
        }
        saved = client.post("/api/autoeval/v1/test-configs", json=second)
        assert saved.status_code == 201, saved.text
    # A new application/session reads committed rows, not component memory.
    with TestClient(create_app(settings)) as client:
        rows = client.get("/api/autoeval/v1/test-configs?limit=200").json()["data"]
        versions = [r for r in rows if r["config_key"] == key]
        assert {r["version"] for r in versions} == {1, 2}
        old = next(r for r in versions if r["version"] == 1)
        assert set(old["items"]) == {"GPQA"}
        new = next(r for r in versions if r["version"] == 2)
        assert set(new["items"]) == {"GPQA", "MMMU-Pro"}
