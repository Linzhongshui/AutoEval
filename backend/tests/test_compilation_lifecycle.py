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


@pytest.mark.asyncio
async def test_compilation_scoped_profiles_do_not_replace_legacy_profile():
    import os

    from sqlalchemy import text

    from autoeval.catalog.models import EvaluationProfile
    from autoeval.catalog.profiles import resolve_profile
    from autoeval.infrastructure.config import get_settings
    from autoeval.infrastructure.db import create_database

    if os.environ.get("AE_INFRA_TEST") != "1":
        pytest.skip("Requires local PostgreSQL")
    engine, sessions = create_database(get_settings())
    legacy, newer = uuid.uuid4(), uuid.uuid4()
    full, lite, other_manifest = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    try:
        async with sessions() as session, session.begin():
            await session.execute(
                text(
                    "CREATE TEMP TABLE evaluation_profile "
                    "(LIKE public.evaluation_profile INCLUDING DEFAULTS) ON COMMIT DROP"
                )
            )
            await session.execute(
                text(
                    "ALTER TABLE pg_temp.evaluation_profile "
                    "ADD COLUMN IF NOT EXISTS compilation_id UUID"
                )
            )
            legacy_profile = EvaluationProfile(
                profile_key="legacy",
                version="v1",
                dataset_name="MMMU-Pro",
                full_manifest_id=full,
                lite_manifest_id=lite,
                contract={},
                sha256="1" * 64,
            )
            newer_profile = EvaluationProfile(
                profile_key="new",
                version="v2",
                dataset_name="MMMU-Pro",
                full_manifest_id=full,
                lite_manifest_id=lite,
                compilation_id=newer,
                contract={},
                sha256="2" * 64,
            )
            unrelated_legacy_profile = EvaluationProfile(
                profile_key="legacy-other",
                version="v1",
                dataset_name="MMMU-Pro",
                full_manifest_id=other_manifest,
                contract={},
                sha256="3" * 64,
            )
            session.add_all([legacy_profile, newer_profile, unrelated_legacy_profile])
            await session.flush()
            assert await resolve_profile(session, "MMMU-Pro", full, legacy) is legacy_profile
            assert await resolve_profile(session, "MMMU-Pro", full, newer) is newer_profile
            assert await resolve_profile(session, "MMMU-Pro", lite, newer) is newer_profile
            assert await resolve_profile(session, "MMMU-Pro", other_manifest, newer) is None
            assert await resolve_profile(session, "MMMU-Pro", other_manifest, legacy) is (
                unrelated_legacy_profile
            )
            assert await resolve_profile(session, "DeepSWE", full, newer) is None
    finally:
        await engine.dispose()
