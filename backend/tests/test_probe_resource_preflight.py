from contextlib import asynccontextmanager
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from autoeval.planning import planning_worker as worker
from autoeval.planning.artifacts import current_preflight
from autoeval.planning.planning_transport import PlanningRemoteContainer


@pytest.mark.parametrize(("change", "reuse"), [
    ({}, True),
    ({"planning_container": ["other", "image"]}, False),
    ({"planning_container": None}, False),
    ({"execution_templates": {"task": "isolated"}}, False),
    ({"resource_ids": ["node", "second"]}, False),
    ({"planner_ready": False}, False),
    ({"preflight_valid_until": "2000-01-01T00:00:00+00:00"}, False),
])
async def test_probe_cache(change, reuse):
    inputs = {"resource_id": "node", "resource_kind": "customer_ssh"}
    snapshot = SimpleNamespace(created_at=datetime.now(UTC), payload={
        **inputs, "resource_ids": ["node"], "planner_ready": True,
        "planning_container": ["container", "image"], **change,
    })
    session = AsyncMock()
    session.scalars.return_value = MagicMock()
    session.scalars.return_value.all.return_value = [snapshot]
    result = await current_preflight(session, inputs, probe_container=["container", "image"])
    assert (result is snapshot) == reuse


async def test_remote_probe_dispatch_without_tasks(monkeypatch):
    adapter = object.__new__(PlanningRemoteContainer)
    adapter.container_id, adapter.image_id, adapter.remote_dir = "container", "image", "/runtime"
    adapter.control = MagicMock()
    adapter.control.command.return_value = '{"planner_ready":true}'
    monkeypatch.setattr(adapter, "validate", AsyncMock())
    monkeypatch.setattr(adapter, "install_runtime", AsyncMock())
    assert (await adapter.preflight())["planning_container"] == ["container", "image"]
    assert adapter.control.command.call_args.args[-1] == b"[]"
    adapter.command(["exec", "-i", "container", "python3", "runtime", "preflight"], b"null")
    assert adapter.control.command.call_count == 2


async def test_probe_validation_failure_never_submits(monkeypatch, caplog):
    session = AsyncMock()
    session.get.return_value = SimpleNamespace(
        state="pending", kind="probe", cancel_requested=False, payload={}
    )

    @asynccontextmanager
    async def sessions():
        yield session

    adapter = AsyncMock()
    adapter.preflight.side_effect = ValueError("private diagnostic")
    monkeypatch.setattr(worker, "transport", AsyncMock(return_value=adapter))
    monkeypatch.setattr(worker, "current_preflight", AsyncMock(return_value=None))
    with pytest.raises(worker.ProbePreflightBlocked):
        await worker.execute_job(sessions, None, "test-job")
    adapter.submit.assert_not_awaited()
    assert "Probe preflight blocked job=test-job type=ValueError" in caplog.text
    assert "private diagnostic" not in caplog.text
