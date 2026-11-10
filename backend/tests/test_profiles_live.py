"""Version and sample binding checks on real PostgreSQL and development S3."""

import os
import uuid

import httpx
import pytest

from autoeval.api import create_app

pytestmark = pytest.mark.skipif(not os.environ.get("AE_INFRA_TEST"), reason="Live SQL/S3 required")


async def test_profile_config_binding_and_snapshot_identity():
    app = create_app()
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as api,
    ):
        prefix = "/api/autoeval/v1"
        key = "fixture-" + uuid.uuid4().hex
        full = await api.post(
            prefix + "/dataset-manifests",
            json={
                "dataset_key": key,
                "name": "Profile fixture",
                "version": "v1",
                "manifest_key": "full",
                "scope": "full",
                "samples": [{"sample_id": "a", "sha256": "a" * 64}],
            },
        )
        assert full.status_code == 201
        full_id = full.json()["data"]["id"]
        profile = {
            "profile_key": key,
            "version": "v1",
            "dataset_name": "GPQA",
            "full_manifest_id": full_id,
            "tool": {
                "family": "aisbench",
                "source_url": "https://example.invalid/fixture",
                "revision": "a" * 40,
                "scorer_reference": "fixture-only",
                "scorer_sha256": "b" * 64,
                "parallelism_owner": "tool",
            },
        }
        response = await api.post(prefix + "/profiles", json=profile)
        assert response.status_code == 201, response.text
        profile_id = response.json()["data"]["id"]
        assert response.json()["data"]["tool_verified"] is False
        assert (await api.post(prefix + "/profiles", json=profile)).json()["data"][
            "id"
        ] == profile_id
        assert (
            await api.post(prefix + "/profiles", json={**profile, "dataset_name": "MMMU-Pro"})
        ).status_code == 409
        params = {"output": 16, "concurrency": 1, "temperature": 0, "top_p": 1, "scope": "Lite"}
        config = {
            "config_key": key,
            "display_name": key,
            "version_label": "v1",
            "expected_version": 0,
            "items": {"GPQA": params},
            "profile_bindings": {"GPQA": profile_id},
        }
        assert (await api.post(prefix + "/test-configs", json=config)).status_code == 422
        config["items"]["GPQA"]["scope"] = "全量"
        response = await api.post(prefix + "/test-configs", json=config)
        assert response.status_code == 201, response.text
        config_id = response.json()["data"]["id"]
        first = (await api.get(prefix + f"/test-configs/{config_id}/execution-spec")).json()["data"]
        assert first["bindings_complete"] is True
        assert first["execution_enabled"] is False
        assert first["spec"]["items"][0]["manifest_id"] == full_id
        assert first["spec"]["items"][0]["sample_count"] == 1
        config["profile_bindings"] = {}
        config["expected_version"] = 1
        config["version_label"] = "v2-draft"
        assert (await api.post(prefix + "/test-configs", json=config)).status_code == 409
        config["profile_bindings"] = {"GPQA": profile_id}
        config["items"]["GPQA"]["output"] = 32
        assert (await api.post(prefix + "/test-configs", json=config)).status_code == 201
        second = (await api.get(prefix + f"/test-configs/{config_id}/execution-spec")).json()[
            "data"
        ]
        assert first == second
