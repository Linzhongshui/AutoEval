import uuid
from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy.dialects import postgresql

from autoeval.configuration import TestConfigVersion as ConfigVersion
from autoeval.configuration import list_configs
from autoeval.registry import Asset, AssetVersion, list_models
from autoeval.resources import ResourceBinding, list_resources
from autoeval.targets import TargetBinding, list_targets


class Result:
    def __init__(self, rows):
        self.rows = rows

    def all(self):
        return self.rows


class PageSession:
    def __init__(self, rows, additional_scalars=()):
        self.rows = rows
        self.additional_scalars = list(additional_scalars)
        self.statements = []

    async def scalars(self, statement):
        self.statements.append(statement)
        if len(self.statements) == 1:
            return Result(self.rows)
        return Result(self.additional_scalars.pop(0))

    async def execute(self, statement):
        self.statements.append(statement)
        return Result(self.rows)


def request(session):
    @asynccontextmanager
    async def context():
        yield session

    return SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(sessions=context)),
        state=SimpleNamespace(request_id="test-request"),
    )


def config_rows():
    return [
        ConfigVersion(
            id=uuid.uuid4(),
            config_key=f"config-{index}",
            display_name="Config",
            version=index + 1,
            version_label="v1",
            kind="custom",
            content_hash="a" * 64,
            created_by="test",
        )
        for index in range(3)
    ]


def model_rows():
    return [
        (
            Asset(id=uuid.uuid4(), asset_key=f"model-{index}", kind="model", name="Model"),
            None,
        )
        for index in range(3)
    ]


def target_rows():
    rows = []
    for index in range(3):
        model = Asset(
            id=uuid.uuid4(), asset_key=f"target-model-{index}", kind="model", name="Model"
        )
        version = AssetVersion(id=uuid.uuid4(), asset_id=model.id, version="v1", metadata_json={})
        target = TargetBinding(
            id=uuid.uuid4(),
            model_version_id=version.id,
            base_url="https://api.deepseek.com",
            remote_model="model",
            credential_ref="a" * 32,
        )
        rows.append((target, model, version, None))
    return rows


def resource_rows():
    return [
        ResourceBinding(
            id=uuid.uuid4(),
            provider_id=uuid.uuid4(),
            binding_key=f"resource-{index}",
            version=1,
            container_id="container",
            image_id="image",
        )
        for index in range(3)
    ]


def row_id(row):
    return str((row[0] if isinstance(row, tuple) else row).id)


def compiled(statement):
    return str(
        statement.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True})
    )


@pytest.mark.parametrize(
    ("handler", "rows"),
    [
        (list_configs, config_rows()),
        (list_models, model_rows()),
        (list_targets, target_rows()),
        (list_resources, resource_rows()),
    ],
)
async def test_list_endpoints_return_a_stable_second_page(handler, rows):
    extras = [[]] if handler is list_configs else []
    first_session = PageSession(rows[:3], extras)
    first = await handler(request(first_session), limit=2)

    second_session = PageSession(rows[2:], extras.copy())
    second = await handler(request(second_session), offset=2, limit=2)

    assert [row["id"] for row in first["data"]] == [row_id(row) for row in rows[:2]]
    assert first["next_offset"] == 2
    assert [row["id"] for row in second["data"]] == [row_id(rows[2])]
    assert second["next_offset"] is None
    for session, offset in ((first_session, 0), (second_session, 2)):
        sql = compiled(session.statements[0])
        assert "LIMIT 3" in sql
        assert f"OFFSET {offset}" in sql
        assert "id DESC" in sql


@pytest.mark.parametrize("handler", [list_configs, list_models, list_targets, list_resources])
@pytest.mark.parametrize(("offset", "limit"), [(-1, 1), (0, 0), (0, 201)])
async def test_list_endpoints_reject_invalid_pagination(handler, offset, limit):
    session = PageSession([])
    with pytest.raises(HTTPException) as exc:
        await handler(request(session), offset=offset, limit=limit)
    assert exc.value.status_code == 422
    assert not session.statements
