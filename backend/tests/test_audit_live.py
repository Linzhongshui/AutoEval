"""Real PostgreSQL audit pagination and immutability checks."""

import os
import uuid

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from autoeval.api import create_app

pytestmark = pytest.mark.skipif(not os.environ.get("AE_INFRA_TEST"), reason="Live SQL required")


async def test_audit_events_are_paginated_and_immutable():
    app = create_app()
    resource_id = "audit-fixture-" + uuid.uuid4().hex
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as api,
    ):
        async with app.state.sessions() as session, session.begin():
            for index in range(3):
                await session.execute(
                    text("""
                        INSERT INTO audit_event
                          (id, actor, action, resource_type, resource_id, outcome, request_id, details)
                        VALUES
                          (:id, 'integration-test', 'test.audit', 'fixture', :resource_id,
                           'succeeded', :request_id, '{}')
                    """),
                    {
                        "id": uuid.uuid4(),
                        "resource_id": resource_id,
                        "request_id": f"fixture-{index}",
                    },
                )
        path = "/api/autoeval/v1/audit-events"
        first = await api.get(path, params={"resource_id": resource_id, "limit": 2})
        assert first.status_code == 200, first.text
        assert len(first.json()["data"]) == 2
        assert first.json()["next_offset"] == 2
        second = await api.get(
            path, params={"resource_id": resource_id, "offset": 2, "limit": 2}
        )
        assert len(second.json()["data"]) == 1
        assert second.json()["next_offset"] is None
        event_id = first.json()["data"][0]["id"]
        with pytest.raises(DBAPIError, match="immutable"):
            async with app.state.sessions() as session, session.begin():
                await session.execute(
                    text("UPDATE audit_event SET outcome = 'failed' WHERE id = :id"),
                    {"id": event_id},
                )
        with pytest.raises(DBAPIError, match="immutable"):
            async with app.state.sessions() as session, session.begin():
                await session.execute(text("DELETE FROM audit_event WHERE id = :id"), {"id": event_id})
