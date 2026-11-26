from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from autoeval.planning import preflight_cache
from autoeval.planning.artifacts import current_preflight


@pytest.mark.asyncio
@pytest.mark.parametrize("condition", ["fresh", "expired", "template_changed", "cleanup_failed"])
async def test_dataset_cache_requires_current_template_and_original_evidence(
    monkeypatch, condition
):
    session = MagicMock()
    sessions = MagicMock()
    sessions.return_value.__aenter__.return_value = session
    session.get = AsyncMock(return_value=SimpleNamespace(credential_ref="ref"))
    session.execute = AsyncMock()
    now = datetime.now(UTC)
    checked_at = now - timedelta(minutes=6 if condition == "expired" else 1)
    evidence = {
        "checked_at": checked_at.isoformat(),
        "container_id": "a" * 64,
        "source_job_id": "old",
    }
    prior = {"execution_ready": True, "preflight_evidence": evidence}
    session.scalar = AsyncMock(
        return_value=None if condition == "cleanup_failed" else {"result": prior}
    )
    template = {"image_id": "image"}
    item = {"assigned_resource_id": "node", "execution_template": template}
    monkeypatch.setattr(preflight_cache, "resource_data", lambda _: {"host": "host"})
    monkeypatch.setattr(
        preflight_cache,
        "execution_template",
        lambda *_: None if condition == "template_changed" else template,
    )
    save = AsyncMock()
    monkeypatch.setattr(preflight_cache, "artifact", save)
    run = AsyncMock(
        return_value={"execution_ready": False}
        if condition == "template_changed"
        else {
            "execution_ready": True,
            "preflight_evidence": {**evidence, "checked_at": now.isoformat()},
        }
    )
    if condition == "cleanup_failed":
        run.side_effect = RuntimeError("cleanup failed")
    operation = preflight_cache.cached_isolated_check(
        sessions, None, uuid4(), item, {}, AsyncMock(), run
    )
    if condition == "cleanup_failed":
        with pytest.raises(RuntimeError, match="cleanup failed"):
            await operation
        save.assert_not_awaited()
        return
    result, reused = await operation
    if condition == "fresh":
        assert reused and result["preflight_evidence"] == evidence
        run.assert_not_awaited()
        save.assert_not_awaited()
    else:
        assert not reused
        run.assert_awaited_once()
        if condition == "expired":
            save.assert_awaited_once()
        else:
            session.scalar.assert_not_awaited()
            save.assert_not_awaited()


@pytest.mark.asyncio
async def test_new_resource_snapshot_cannot_extend_expired_dataset_evidence():
    now = datetime.now(UTC)
    inputs = {"resource_id": "node", "resource_kind": "customer_ssh"}
    latest = SimpleNamespace(
        created_at=now,
        payload={
            **inputs,
            "preflight_valid_until": (now - timedelta(seconds=1)).isoformat(),
        },
    )
    session = AsyncMock()
    rows = MagicMock()
    rows.all.return_value = [latest]
    session.scalars.return_value = rows
    assert await current_preflight(session, inputs) is None
