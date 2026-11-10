"""SQL/S3 smoke orchestration with a simulated model boundary; sends no paid requests."""

import os
import uuid

import pytest
from sqlalchemy import select

from autoeval import native_smoke
from autoeval.config import get_settings
from autoeval.db import create_database
from autoeval.models import RunEvent, RunSnapshot
from autoeval.resources import ResourceBinding
from autoeval.targets import TargetBinding

pytestmark = pytest.mark.skipif(not os.environ.get("AE_INFRA_TEST"), reason="Live SQL/S3 required")


async def test_native_smoke_records_valid_transitions_without_secret_snapshot(monkeypatch):
    engine, sessions = create_database(get_settings())
    try:
        async with sessions() as session:
            target = await session.scalar(
                select(TargetBinding).where(TargetBinding.remote_model == "deepseek-flash").limit(1)
            )
            resource = await session.scalar(select(ResourceBinding).limit(1))
            assert target and resource
        monkeypatch.setattr(
            native_smoke.FileSecretStore, "get", lambda *args: "fixture-secret-only"
        )
        monkeypatch.setattr(
            native_smoke,
            "inspect_executor",
            lambda *args: {"running": True, "image_id": resource.image_id},
        )
        calls = []

        def fake_invoke(settings, container_id, payload):
            calls.append(payload["operation"])
            if payload["operation"] == "prompt_gpqa_0shot":
                return {"prompt": "Fixture prompt", "tool_revision": "a" * 40}
            assert payload["api_key"] == "fixture-secret-only"
            assert payload["max_tokens"] == 32
            return {
                "state": "succeeded",
                "prompt": "Fixture prompt",
                "response": "A",
                "finish_reason": "stop",
                "error_code": None,
                "usage": {"input_tokens": 1, "output_tokens": 1},
            }

        monkeypatch.setattr(native_smoke, "invoke", fake_invoke)
        result = await native_smoke.run_smoke(target.id, resource.id)
        assert result["state"] == "completed"
        assert calls == ["prompt_gpqa_0shot", "infer_gpqa_smoke"]
        run_id = uuid.UUID(result["run_id"])
        async with sessions() as session:
            snapshot = await session.scalar(select(RunSnapshot).where(RunSnapshot.run_id == run_id))
            assert "api_key" not in str(snapshot.canonical_body)
            assert "fixture-secret-only" not in str(snapshot.canonical_body)
            events = (
                await session.scalars(
                    select(RunEvent).where(RunEvent.run_id == run_id).order_by(RunEvent.seq)
                )
            ).all()
            assert [e.type for e in events] == [
                "accepted",
                "queued",
                "preparing",
                "running",
                "aggregating",
                "completed",
            ]
            assert [e.seq for e in events] == [1, 2, 3, 4, 5, 6]
    finally:
        await engine.dispose()
