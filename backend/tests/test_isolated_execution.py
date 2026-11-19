from types import SimpleNamespace
from uuid import uuid4

import pytest
from pydantic import ValidationError

from autoeval.evaluation.evaluation_tasks import SubmitTask
from autoeval.planning.planning_transport import IsolatedPlanningContainer, execution_template


@pytest.mark.parametrize(
    ("subcommand", "tool"),
    [
        ("llm_accuracy", "aisbench"),
        ("harbor_agent", "harbor"),
        ("peir", "peir"),
        ("agentx", "agentx"),
    ],
)
def test_template_requires_selected_node_to_offer_exact_tool_revision(tmp_path, subcommand, tool):
    import json

    node = str(uuid4())
    image = "sha256:" + "1" * 64
    file = tmp_path / "nodes.json"
    file.write_text(
        json.dumps(
            {
                node: {
                    "executors": {
                        tool: {"revision": "fixed", "image_id": image, "private_docker": True}
                    }
                },
            }
        )
    )
    settings = SimpleNamespace(planning_container_config=str(file))
    task = {"compilation": {"config": {"subcommand": subcommand}}, "tool": {"revision": "fixed"}}
    assert execution_template(settings, node, task)["image_id"] == image
    assert execution_template(settings, uuid4(), task) is None
    task["tool"]["revision"] = "different"
    assert execution_template(settings, node, task) is None


def test_container_identity_must_match_owner_even_when_name_and_image_match():
    import json

    owner = str(uuid4())
    adapter = object.__new__(IsolatedPlanningContainer)
    adapter.owner = owner
    adapter.name = "autoeval-task-" + owner
    adapter.image_id = "sha256:" + "1" * 64
    row = {
        "Name": "/" + adapter.name,
        "Image": adapter.image_id,
        "Config": {"Labels": {"autoeval.dataset_execution": str(uuid4())}},
    }
    adapter.control = SimpleNamespace(
        command=lambda _, argv: b"container-id" if argv[1] == "ps" else json.dumps([row]).encode()
    )
    with pytest.raises(ValueError, match="ownership mismatch"):
        adapter._find(None)


def test_submission_rejects_local_resource_kind():
    with pytest.raises(ValidationError) as exc:
        SubmitTask.model_validate({"resource_kind": "docker_local"})
    assert any(error["loc"] == ("resource_kind",) for error in exc.value.errors())


def test_recover_created_container_and_remove_only_selected_child():
    import json
    from contextlib import nullcontext

    rows = {}
    lost_reply = True

    def command(_, argv):
        nonlocal lost_reply
        _, action, *args = argv
        if action == "ps":
            name = args[-1].removeprefix("name=^/").removesuffix("$")
            return name.encode() if name in rows else b""
        if action == "create":
            name = args[args.index("--name") + 1]
            assert name not in rows
            rows[name] = {
                "Id": name,
                "Name": "/" + name,
                "Image": image,
                "Config": {
                    "Labels": {
                        "autoeval.dataset_execution": args[args.index("--label") + 1].split("=")[1]
                    }
                },
                "State": {"Status": "created", "Running": False},
            }
            if lost_reply:
                lost_reply = False
                raise OSError("SSH reply lost after create")
            return name.encode()
        if action == "inspect":
            return json.dumps([rows[args[-1]]]).encode()
        if action == "start":
            rows[args[-1]]["State"] = {"Status": "running", "Running": True}
        elif action == "rm":
            del rows[args[-1]]
        else:
            raise AssertionError(argv)
        return b""

    def adapter(owner):
        result = object.__new__(IsolatedPlanningContainer)
        result.owner = owner
        result.name = "autoeval-task-" + owner
        result.image_id = image
        result.template = {"family": "aisbench"}
        result.control = SimpleNamespace(command=command, connect=nullcontext)
        return result

    image = "sha256:" + "2" * 64
    first = adapter(str(uuid4()))
    second = adapter(str(uuid4()))
    with pytest.raises(OSError, match="reply lost"):
        first._ensure()
    assert second._ensure() == second.name
    recovered = adapter(first.owner)
    assert recovered._ensure() == first.name
    assert set(rows) == {first.name, second.name}
    assert recovered._remove()
    assert recovered._remove()
    assert rows[second.name]["State"]["Running"]


@pytest.mark.asyncio
async def test_failed_removal_retains_lease_until_reconciled(monkeypatch):
    from contextlib import asynccontextmanager
    from unittest.mock import AsyncMock

    from autoeval.evaluation import isolated_cleanup

    owner = uuid4()
    row = SimpleNamespace(resource_id=uuid4(), template={}, state="cleanup_pending")
    remove = AsyncMock(side_effect=[OSError("SSH disconnected"), True])
    release = AsyncMock()

    @asynccontextmanager
    async def transaction():
        yield

    @asynccontextmanager
    async def sessions():
        yield SimpleNamespace(begin=transaction, get=AsyncMock(return_value=row))

    monkeypatch.setattr(
        isolated_cleanup,
        "isolated_transport",
        AsyncMock(return_value=SimpleNamespace(remove=remove)),
    )
    monkeypatch.setattr(isolated_cleanup, "release", release)

    await isolated_cleanup.reclaim_child(sessions, None, owner)
    assert row.state == "cleanup_pending"
    release.assert_not_awaited()

    await isolated_cleanup.reclaim_child(sessions, None, owner)
    await isolated_cleanup.reclaim_child(sessions, None, owner)
    assert row.state == "cleaned"
    assert remove.await_count == 2
    assert release.await_count == 1
    assert release.await_args.args[1] == owner


@pytest.mark.asyncio
@pytest.mark.parametrize("family", ["peir", "agentx"])
async def test_tool_dispatch_contract_with_real_docker(family):
    import asyncio
    import os
    import subprocess
    from contextlib import nullcontext

    image = os.getenv("AE_ISOLATED_TEST_IMAGE")
    if not image:
        pytest.skip("Set AE_ISOLATED_TEST_IMAGE to a local Python image ID")

    def command(_, argv, payload=None):
        return subprocess.run(
            argv, input=payload, capture_output=True, check=True, timeout=20
        ).stdout

    def executor():
        owner = uuid4()
        connection = SimpleNamespace(workdir="/tmp", owner_id=owner)
        adapter = IsolatedPlanningContainer(
            connection, owner, {"family": family, "image_id": image}
        )
        adapter.control = SimpleNamespace(command=command, connect=nullcontext)
        return adapter, str(owner)

    async def wait_for(adapter, job, desired):
        for _ in range(50):
            if (await adapter.status(job)).state == desired:
                return
            await asyncio.sleep(0.1)
        pytest.fail(f"{family} fixture did not enter {desired}")

    left, left_key = executor()
    right, right_key = executor()
    try:
        assert await left.ensure() != await right.ensure()
        running = {"kind": "framework_smoke", "duration_seconds": 20}
        quick = {"kind": "framework_smoke", "duration_seconds": 2}
        left_job = await left.submit(running, left_key)
        right_job = await right.submit(quick, right_key)
        await wait_for(left, left_job, "running")
        await wait_for(right, right_job, "running")
        await left.cancel(left_job, "fixture-cancel")
        await wait_for(left, left_job, "cancelled")
        assert await left.remove()

        await wait_for(right, right_job, "succeeded")
        from autoeval.resources.docker_executor import DockerExecutor

        result = await DockerExecutor.collect(right, right_job)
        assert result["result"]["model_called"] is False
    finally:
        await asyncio.gather(left.remove(), right.remove())
