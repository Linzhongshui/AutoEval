"""SSH registry SQL checks; preflight requires a separately enabled local simulator."""

import os
import uuid

import httpx
import pytest

from autoeval.api import create_app

pytestmark = pytest.mark.skipif(
    not os.environ.get("AE_INFRA_TEST"), reason="Live PostgreSQL required"
)


async def test_ssh_resource_registration_is_private_versioned_and_persistent():
    app = create_app()
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as api,
    ):
        prefix = "/api/autoeval/v1/ssh-resources"
        secret = "fixture-only-not-real-password"
        credential = await api.post(
            prefix + "/credentials", json={"auth_kind": "password", "value": secret}
        )
        assert credential.status_code == 201 and secret not in credential.text
        body = {
            "binding_key": "ssh-registry-" + uuid.uuid4().hex,
            "host": "127.0.0.1",
            "port": 1,
            "username": "autoeval",
            "fingerprint": "SHA256:" + "A" * 43,
            "workdir": "/work",
            "auth_kind": "password",
            "credential_ref": credential.json()["data"]["credential_ref"],
        }
        response = await api.post(prefix, json=body)
        assert response.status_code == 201, response.text
        assert secret not in response.text and "credential_ref" not in response.text
        assert response.json()["data"]["evaluation_ready"] is False
        assert (await api.post(prefix, json=body)).status_code == 409
        assert (
            await api.post(
                prefix, json={**body, "binding_key": "invalid-" + uuid.uuid4().hex, "workdir": "/"}
            )
        ).status_code == 422
        resource_id = response.json()["data"]["id"]
        assert (await api.post(f"{prefix}/{resource_id}/validate")).status_code == 409
        listing = await api.get(prefix + "?limit=1")
        assert (
            listing.status_code == 200
            and "credential_ref" not in listing.text
            and secret not in listing.text
        )
        assert (await api.get(prefix + "?limit=0")).status_code == 422
