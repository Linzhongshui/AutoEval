from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from autoeval.evaluation.archived_executor_files import archive_directory, archived_files
from autoeval.evaluation.models import DatasetExecution, ExecutionShard


@pytest.mark.parametrize("model", [DatasetExecution, ExecutionShard])
async def test_browse_only_verified_native_outputs_for_the_selected_job(monkeypatch, model):
    run = uuid4()
    job = model(
        id=uuid4(),
        task_id="deepswe",
        payload={"compilation": {"config": {"subcommand": "harbor_agent"}}},
    )
    collection = SimpleNamespace(created_at=datetime.now(UTC))
    session = AsyncMock()
    session.scalar.return_value = collection
    session.scalars.return_value = []
    files = {
        "agent/trajectory.json": '{"api_key": "private-test"}',
        "result.json": "{}",
        "../../config.json": "private-test",
    }
    payload = {"cases": [{"harbor_artifact": {"trial_name": "trial1", "files": files}}]}

    def read(settings, reference):
        assert reference is collection
        return payload

    monkeypatch.setattr("autoeval.evaluation.archived_executor_files.read_manifest", read)
    listing = await archived_files(session, None, run, job, "", 0)
    assert listing["archived"]
    assert [e["name"] for e in listing["entries"]] == [
        "trial1/agent/trajectory.json",
        "trial1/result.json",
    ]
    query = session.scalar.await_args.args[0].compile().params.values()
    assert run in query
    assert (job.task_id if model is DatasetExecution else f"round-shard:{job.id}") in query
    root = await archived_files(session, None, run, job, "", 0, directory=True)
    assert [(e["name"], e["directory"]) for e in root["entries"]] == [("trial1", True)]
    children = await archived_files(session, None, run, job, "trial1", 0, directory=True)
    assert [(e["name"], e["directory"]) for e in children["entries"]] == [
        ("agent", True),
        ("result.json", False),
    ]
    preview = await archived_files(session, None, run, job, "trial1/agent/trajectory.json", 0)
    assert preview["state"] == "text" and "private-test" not in preview["content"]
    missing = await archived_files(session, None, run, job, "../../config.json", 0)
    assert missing["state"] == "missing_file"
    assert await archived_files(session, None, run, job, "", 100) == {
        "state": "directory",
        "archived": True,
        "entries": [],
        "more": False,
    }

    def damaged(settings, reference):
        raise ValueError("Manifest integrity mismatch")

    monkeypatch.setattr("autoeval.evaluation.archived_executor_files.read_manifest", damaged)
    assert await archived_files(session, None, run, job, "", 0) == {"state": "unavailable"}


def test_archive_directory_paginates_immediate_children():
    files = {f"trial/agent/{i:03}.json": ("测", 10) for i in range(101)}
    files["trial-other/agent/extra.json"] = ("{}", 11)
    first = archive_directory(files, "trial/agent", 0)
    assert len(first["entries"]) == 100 and first["more"]
    last = archive_directory(files, "trial/agent", 100)
    assert not last["more"]
    assert last["entries"] == [{"name": "100.json", "size": 3, "directory": False, "mtime": 10}]
    assert archive_directory(files, "trial/../trial-other", 0) == {"state": "missing_file"}
