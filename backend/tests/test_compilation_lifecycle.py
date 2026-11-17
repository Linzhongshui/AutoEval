import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from autoeval.evaluation.service import resolve_inputs
from autoeval.infrastructure.config import Settings
from autoeval.planning.routes import PlanInput


@pytest.mark.asyncio
async def test_archived_compilation_cannot_be_preflighted_or_submitted():
    compilation_id = uuid.uuid4()
    body = PlanInput(
        target_id=uuid.uuid4(),
        resource_id=uuid.uuid4(),
        resource_kind="customer_ssh",
        tasks=[
            {
                "task_id": "AutomationBench",
                "dataset": "AutomationBench",
                "compilation_id": compilation_id,
                "manifest_id": uuid.uuid4(),
            }
        ],
    )
    session = SimpleNamespace(
        get=AsyncMock(
            return_value=SimpleNamespace(base_url="https://example.com/v1", remote_model="model")
        )
    )
    with pytest.raises(HTTPException) as error:
        await resolve_inputs(session, Settings(archived_compilation_ids=[compilation_id]), body)
    assert error.value.status_code == 409
    assert session.get.await_count == 1


@pytest.mark.asyncio
async def test_compilation_resource_binding_is_checked_before_tool_execution():
    body = PlanInput(
        target_id=uuid.uuid4(),
        resource_id=uuid.uuid4(),
        resource_kind="customer_ssh",
        tasks=[
            {
                "task_id": "AutomationBench",
                "dataset": "AutomationBench",
                "compilation_id": uuid.uuid4(),
                "manifest_id": uuid.uuid4(),
            }
        ],
    )
    asset_id = uuid.uuid4()
    session = SimpleNamespace(
        get=AsyncMock(
            side_effect=[
                SimpleNamespace(base_url="https://example.com/v1", remote_model="model"),
                SimpleNamespace(payload={"runtime_config": {"resource_ids": [str(uuid.uuid4())]}}),
                SimpleNamespace(id=body.tasks[0].manifest_id, dataset_version_id=uuid.uuid4()),
                SimpleNamespace(asset_id=asset_id),
                SimpleNamespace(asset_key="AutomationBench"),
            ]
        ),
        scalar=AsyncMock(return_value=object()),
    )
    with pytest.raises(HTTPException) as error:
        await resolve_inputs(session, Settings(), body)
    assert error.value.status_code == 422
    assert "执行资源" in error.value.detail
