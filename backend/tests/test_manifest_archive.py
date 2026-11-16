import uuid

import pytest
from fastapi import HTTPException

from autoeval.config import get_settings
from autoeval.planning import PlanInput, resolve_inputs


async def test_archived_manifest_blocks_new_submissions_without_reading_history(monkeypatch):
    identifier = uuid.uuid4()
    settings = get_settings().model_copy(update={"archived_manifest_ids": [identifier]})

    async def target(*args):
        return {"model": "TEST", "base_url": "https://fixture.invalid"}

    monkeypatch.setattr("autoeval.evaluation.service.target_data", target)
    body = PlanInput(
        target_id=uuid.uuid4(),
        resource_id=uuid.uuid4(),
        resource_kind="customer_ssh",
        tasks=[
            {
                "task_id": "GPQA",
                "dataset": "GPQA",
                "compilation_id": uuid.uuid4(),
                "manifest_id": identifier,
            }
        ],
    )
    with pytest.raises(HTTPException) as exc:
        await resolve_inputs(object(), settings, body)
    assert exc.value.status_code == 409
    assert "已归档" in exc.value.detail
