import uuid

import httpx

from autoeval.entrypoints.api import create_app
from autoeval.infrastructure.config import get_settings


async def test_unavailable_probe_consumer_does_not_enqueue(monkeypatch):
    async def unavailable(*args):
        return False

    async def forbidden(*args, **kwargs):
        raise AssertionError("No worker: must not create a paid probe intent")

    monkeypatch.setattr("autoeval.planning.probe_dispatch.consumer_ready", unavailable)
    monkeypatch.setattr("autoeval.planning.routes.enqueue", forbidden)
    app = create_app(get_settings())
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://test") as client,
    ):
        result = await client.post(
            "/api/autoeval/v1/planning/probes",
            json={
                "target_id": str(uuid.uuid4()),
                "resource_id": str(uuid.uuid4()),
                "resource_kind": "customer_ssh",
                "concurrency": [1],
            },
        )
        assert result.status_code == 503
        assert "探测执行器未启用" in result.json()["error"]["message"]


async def test_probe_lease_cutoff_does_not_advertise_historical_jobs():
    import os
    from datetime import UTC, datetime, timedelta

    import pytest
    from sqlalchemy import text

    from autoeval.infrastructure.db import create_database
    from autoeval.planning.probe_dispatch import consumer_key, consumer_ready

    if not os.getenv("AE_INFRA_TEST"):
        pytest.skip("Explicit PostgreSQL validation required")
    engine, sessions = create_database(get_settings())
    cutoff = int(datetime.now(UTC).timestamp())
    async with engine.connect() as lease:
        try:
            await lease.execute(
                text("SELECT pg_advisory_lock_shared(hashtext(:key))"), {"key": consumer_key()}
            )
            await lease.execute(
                text("SELECT pg_advisory_lock_shared(1095062608, :cutoff)"), {"cutoff": cutoff}
            )
            async with sessions() as s:
                assert await consumer_ready(s)
            async with sessions() as s:
                assert not await consumer_ready(
                    s, uuid.uuid4(), datetime.now(UTC) - timedelta(minutes=5)
                )
            async with sessions() as s:
                assert await consumer_ready(s, uuid.uuid4(), datetime.now(UTC))
        finally:
            await lease.execute(text("SELECT pg_advisory_unlock_all()"))
    await engine.dispose()
