"""Manual retry of a terminal sample with incomplete historical receipts."""

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from autoeval.catalog.standard_inputs import digest
from autoeval.evaluation import resume_preview


@pytest.mark.asyncio
async def test_manual_retry_binds_current_template_and_one_historical_sample(monkeypatch):
    samples = [
        {"sample_id": f"q{i}", "sha256": str(i) * 64, "tool_case_id": str(i)} for i in range(2)
    ]
    task = {
        "dataset": "GPQA",
        "samples": samples,
        "attempts": 1,
        "assigned_resource_id": "node",
        "execution_template": {"image_id": "original"},
        "compilation": {"config": {"subcommand": "llm_accuracy", "params": {}}},
    }
    frozen = {"inputs": {"tasks": [task]}}
    snapshot = SimpleNamespace(canonical_body=frozen, sha256=digest(frozen))
    run = SimpleNamespace(
        id=uuid.uuid4(), trigger_scope="local-operator:orchestration", state="failed"
    )
    job = SimpleNamespace(id=uuid.uuid4(), state="failed", payload=task, summary={})
    target = {"dataset_key": "GPQA", "sample_id": "q1"}
    template = {"image_id": "replacement"}
    monkeypatch.setattr(resume_preview, "execution_template", lambda *_: template)
    for name in ("follow_up_target_blocker", "follow_up_budget_blocker"):
        monkeypatch.setattr(resume_preview, name, AsyncMock(return_value=None))

    async def preview(operation="case_retry"):
        session = SimpleNamespace(
            scalar=AsyncMock(side_effect=[snapshot, None, None]),
            scalars=AsyncMock(side_effect=[[], [job], [], []]),
        )
        return await resume_preview.preview_scope(
            session, None, run, operation, target if operation == "case_retry" else {}
        )

    result = await preview()
    assert not result.selection["blockers"]
    assert set(result.selection["warnings"]) == {
        "previous_dispatch_unknown",
        "using_current_template",
    }
    (shard,) = result.shards
    assert shard["samples"] == samples[1:]
    assert shard["compilation"]["config"]["params"]["dataset_test_range"] == "[1:2]"
    assert shard["execution_template"] == template
    assert snapshot.sha256 == digest(frozen)
    other_task = {**task, "dataset": "MMMU-Pro", "assigned_resource_id": "second-node"}
    other_job = SimpleNamespace(id=uuid.uuid4(), state="failed", payload=other_task, summary={})
    multi_body = {"inputs": {"tasks": [task, other_task]}}
    multi_snapshot = SimpleNamespace(canonical_body=multi_body, sha256=digest(multi_body))
    other_template = {"image_id": "second-image"}
    monkeypatch.setattr(
        resume_preview,
        "execution_template",
        lambda _, node, task: other_template if node == "second-node" else template,
    )

    async def batch_preview():
        session = SimpleNamespace(
            scalar=AsyncMock(side_effect=[multi_snapshot, None, None]),
            scalars=AsyncMock(side_effect=[[], [job, other_job], [], []]),
        )
        return await resume_preview.preview_scope(
            session,
            None,
            run,
            "case_retry",
            {"cases": [target, {**target, "dataset_key": "MMMU-Pro"}]},
        )

    batch = await batch_preview()
    assert batch.selection["sample_count"] == 2
    assert [shard["samples"] for shard in batch.shards] == [samples[1:], samples[1:]]
    other_template["image_id"] = "second-image-changed"
    assert (await batch_preview()).scope_sha256 != batch.scope_sha256

    template["image_id"] = "changed-again"
    assert (await preview()).scope_sha256 != result.scope_sha256
    job.state = "running"
    assert "samples_unresolved" in (await preview()).selection["blockers"]
    run.state = job.state = "cancelled"
    job.started_at = True
    assert "samples_unresolved" in (await preview("resume")).selection["blockers"]
