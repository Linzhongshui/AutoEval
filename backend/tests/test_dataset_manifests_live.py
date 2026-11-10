"""Real PostgreSQL and development S3 manifest round trips, no benchmark claims."""

import os
import uuid

import httpx
import pytest

from autoeval.api import create_app

pytestmark = pytest.mark.skipif(not os.environ.get("AE_INFRA_TEST"), reason="Live SQL/S3 required")


async def test_full_lite_immutability_and_membership():
    app = create_app()
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as api,
    ):
        path = "/api/autoeval/v1/dataset-manifests"
        body = {
            "dataset_key": "fixture-" + uuid.uuid4().hex,
            "name": "Integration fixture (not benchmark)",
            "version": "v1",
            "manifest_key": "full",
            "scope": "full",
            "samples": [
                {"sample_id": "a", "sha256": "a" * 64},
                {"sample_id": "b", "sha256": "b" * 64},
            ],
        }
        full = await api.post(path, json=body)
        assert full.status_code == 201, full.text
        full_id = full.json()["data"]["id"]
        assert (
            await api.post(path, json={**body, "manifest_key": "other-full"})
        ).status_code == 409
        repeated = await api.post(path, json=body)
        assert repeated.json()["data"]["id"] == full_id
        assert (
            await api.post(path, json={**body, "samples": body["samples"][:1]})
        ).status_code == 409
        lite = {
            **body,
            "manifest_key": "lite-1",
            "scope": "lite",
            "parent_id": full_id,
            "samples": body["samples"][:1],
        }
        response = await api.post(path, json=lite)
        assert response.status_code == 201, response.text
        assert response.json()["data"]["sample_count"] == 1
        assert (
            await api.post(
                path,
                json={
                    **lite,
                    "manifest_key": "invalid",
                    "samples": [{"sample_id": "a", "sha256": "c" * 64}],
                },
            )
        ).status_code == 422
        assert (await api.post(path, json={**lite, "version": "v2"})).status_code == 422
        page = await api.get(path + "?limit=1")
        assert len(page.json()["data"]) == 1
        assert page.json()["next_offset"] is not None
