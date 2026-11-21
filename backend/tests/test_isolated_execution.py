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
        if action == "image":
            assert args[-1] == image
            return image.encode()
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
    with pytest.raises(ValueError, match="recorded task container is missing"):
        recovered._ensure()
    assert set(rows) == {second.name}
    assert rows[second.name]["State"]["Running"]


@pytest.mark.asyncio
async def test_failed_removal_retains_lease_until_reconciled(monkeypatch):
    from contextlib import asynccontextmanager
    from unittest.mock import AsyncMock

    from autoeval.evaluation import isolated_cleanup

    owner = uuid4()
    row = SimpleNamespace(
        resource_id=uuid4(), template={}, state="cleanup_pending", container_id=None
    )
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
    assert row.cleanup_attempted_at is not None

    await isolated_cleanup.reclaim_child(sessions, None, owner)
    await isolated_cleanup.reclaim_child(sessions, None, owner)
    assert row.state == "cleaned"
    assert remove.await_count == 2
    assert release.await_count == 1
    assert release.await_args.args[1] == owner


@pytest.mark.asyncio
@pytest.mark.parametrize("family", ["peir", "agentx"])
@pytest.mark.parametrize("transport_kind", ["local", "ssh"])
async def test_tool_dispatch_contract_with_real_docker(family, transport_kind):
    import asyncio
    import os
    import subprocess
    from contextlib import nullcontext

    ssh_config = os.getenv("AE_ISOLATED_SSH_CONFIG") if transport_kind == "ssh" else None
    if transport_kind == "ssh" and not ssh_config:
        pytest.skip("Set AE_ISOLATED_SSH_CONFIG to an approved test node configuration")
    image = os.getenv("AE_ISOLATED_TEST_IMAGE") if transport_kind == "local" else None
    if transport_kind == "local" and not image:
        pytest.skip("Set AE_ISOLATED_TEST_IMAGE to a local Python image ID")

    def command(_, argv, payload=None):
        return subprocess.run(
            argv, input=payload, capture_output=True, check=True, timeout=20
        ).stdout

    def executor():
        owner = uuid4()
        if ssh_config:
            import json
            from pathlib import Path

            from pydantic import SecretStr

            from autoeval.infrastructure.config import get_settings
            from autoeval.infrastructure.secrets import FileSecretStore
            from autoeval.resources.ssh_executor import SSHConnection

            config = json.loads(Path(ssh_config).read_text(encoding="utf-8"))
            remote_image = config.pop("image_id")
            credential_ref = config.pop("credential_ref")
            credential = FileSecretStore(get_settings().secret_store_path).get(credential_ref)
            connection = SSHConnection(**config, owner_id=owner, credential=SecretStr(credential))
            return IsolatedPlanningContainer(
                connection, owner, {"family": family, "image_id": remote_image}
            ), str(owner)
        connection = SimpleNamespace(workdir="/tmp", owner_id=owner)
        adapter = IsolatedPlanningContainer(
            connection, owner, {"family": family, "image_id": image}
        )
        adapter.control = SimpleNamespace(command=command, connect=nullcontext)
        return adapter, str(owner)

    async def wait_for(adapter, job, desired):
        for _ in range(50):
            observed = await adapter.status(job)
            if observed.state == desired:
                return
            if observed.state in {"failed", "succeeded", "cancelled"}:
                pytest.fail(f"{family} fixture reached {observed.state} before {desired}")
            await asyncio.sleep(0.1)
        pytest.fail(f"{family} fixture did not enter {desired}")

    from autoeval_runtime.planning_runtime import ADAPTOR_REVISION

    fixture_runtime = b"""
import time


def validate_spec(spec):
    assert spec["kind"] == "adaptor"
    assert spec["tool"]["family"] in {"peir", "agentx"}


def controlled_failure_reason(spec, exc):
    return spec["tool"]["family"] + "_fixture_failed"


def execute(folder, spec):
    tool = spec["tool"]
    time.sleep(tool["delay"])
    if tool["fail"]:
        raise RuntimeError("fixture failure")
    print("x" * (1024 * 1024 + 1))
    print("fixture-log:" + folder.name)
    return {"family": tool["family"], "child_id": folder.name, "model_called": False}
"""

    def spec(delay, *, fail=False):
        return {
            "kind": "adaptor",
            "compilation": {"adaptor_revision": ADAPTOR_REVISION},
            "tool": {"family": family, "delay": delay, "fail": fail},
            "credential": "fixture-only",
        }

    left, left_key = executor()
    right, right_key = executor()
    failed, failed_key = executor()
    for adapter in (left, right, failed):
        adapter.files["planning_runtime.py"] = fixture_runtime
    try:
        assert await left.ensure() != await right.ensure()
        left_job = await left.submit(spec(90 if ssh_config else 25), left_key)
        right_job = await right.submit(spec(30 if ssh_config else 8), right_key)
        await wait_for(left, left_job, "running")
        await wait_for(right, right_job, "running")
        await left.cancel(left_job, "fixture-cancel")
        await wait_for(left, left_job, "cancelled")
        assert await left.remove()

        await wait_for(right, right_job, "succeeded")
        from autoeval.resources.docker_executor import DockerExecutor

        result = (
            await right.collect(right_job)
            if ssh_config
            else await DockerExecutor.collect(right, right_job)
        )
        assert result["result"] == {
            "family": family,
            "child_id": right_key,
            "model_called": False,
        }

        if ssh_config:
            log = await right.collect_log(right_job)
            assert len(log["content"]) > 1024 * 1024
            assert log["content"].endswith("fixture-log:" + right_key + "\n")
            assert log["truncated"] is False

        await failed.ensure()
        failed_job = await failed.submit(spec(1, fail=True), failed_key)
        await wait_for(failed, failed_job, "failed")
        assert (await failed.status(failed_job)).reason == family + "_fixture_failed"
        assert await failed.remove()
        assert (await right.status(right_job)).state == "succeeded"
    finally:
        await asyncio.gather(left.remove(), right.remove(), failed.remove())


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["collect", "collect_log"])
async def test_artifact_read_requires_owned_container_before_remote_io(method, monkeypatch):
    from unittest.mock import AsyncMock

    from autoeval.planning.planning_transport import PlanningRemoteContainer

    adapter = object.__new__(IsolatedPlanningContainer)
    adapter.validate = AsyncMock(side_effect=ValueError("Task container ownership mismatch"))
    remote_read = AsyncMock()
    monkeypatch.setattr(PlanningRemoteContainer, method, remote_read)

    with pytest.raises(ValueError, match="ownership mismatch"):
        await getattr(adapter, method)(None)

    adapter.validate.assert_awaited_once()
    remote_read.assert_not_awaited()


def test_recovered_container_rejects_replacement_with_same_labels():
    import json

    adapter = object.__new__(IsolatedPlanningContainer)
    adapter.owner = str(uuid4())
    adapter.name = "autoeval-task-" + adapter.owner
    adapter.image_id = "sha256:" + "1" * 64
    adapter.expected_container_id = "original-id"
    row = {
        "Id": "replacement-id",
        "Name": "/" + adapter.name,
        "Image": adapter.image_id,
        "Config": {"Labels": {"autoeval.dataset_execution": adapter.owner}},
    }
    adapter.control = SimpleNamespace(
        command=lambda _, argv: (
            row["Id"].encode() if argv[1] == "ps" else json.dumps([row]).encode()
        )
    )

    with pytest.raises(ValueError, match="ownership mismatch"):
        adapter._find(None)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("family", "subcommand"),
    [
        ("aisbench", "llm_accuracy"),
        ("harbor", "harbor_agent"),
    ],
)
async def test_native_tool_isolated_over_ssh(family, subcommand):
    import asyncio
    import json
    import os
    from pathlib import Path

    from pydantic import SecretStr

    from autoeval.infrastructure.config import get_settings
    from autoeval.infrastructure.secrets import FileSecretStore
    from autoeval.resources.ssh_executor import SSHConnection

    config_path = os.getenv("AE_ISOLATED_NATIVE_SSH_CONFIG")
    if not config_path:
        pytest.skip("Approved native SSH fixtures required")
    fixture = json.loads(Path(config_path).read_text(encoding="utf-8"))[family]
    store = FileSecretStore(get_settings().secret_store_path)
    owner = uuid4()
    connection_fields = dict(fixture["connection"])
    ssh_credential = store.get(connection_fields.pop("credential_ref"))
    connection = SSHConnection(
        **connection_fields, owner_id=owner, credential=SecretStr(ssh_credential)
    )
    template = fixture["template"]
    spec = fixture["spec"]
    assert template["family"] == family
    assert template["revision"] == spec["tool"]["revision"]
    assert spec["kind"] == "adaptor"
    assert spec["compilation"]["config"]["subcommand"] == subcommand
    assert "credential" not in spec
    spec["credential"] = store.get(fixture["model_credential_ref"])
    adapter = IsolatedPlanningContainer(connection, owner, template)
    try:
        await adapter.ensure()
        check = {key: spec[key] for key in ("compilation", "tool")}
        check.update(task_id=str(owner), dataset=fixture["dataset"])
        preflight = await adapter.preflight([check])
        assert preflight["execution_ready"], preflight["blocking_reasons"]

        job = await adapter.submit(spec, str(owner))
        async with asyncio.timeout(300):
            while True:
                observed = await adapter.status(job)
                if observed.state in {"succeeded", "failed", "cancelled", "unknown"}:
                    break
                await asyncio.sleep(1)
        assert observed.state == "succeeded", observed.reason
        result = (await adapter.collect(job))["result"]
        assert result.get("tool_exit_code", 0) == 0
        from autoeval.catalog.datasets import canonical_manifest
        from autoeval.reporting.result_identity import normalize_result_identities
        from autoeval.reporting.unified_outputs import parse_output

        dataset = fixture["dataset"]
        samples = fixture["samples"]
        normalized = normalize_result_identities(
            result["unified_result"], dataset, spec["compilation"]["config"], samples
        )
        expected = {dataset: [sample["sample_id"] for sample in samples]}
        cases, summary = parse_output(canonical_manifest(normalized), expected, dataset)
        assert {case["sample_id"] for case in cases} == set(expected[dataset])
        assert summary["validity"] == "complete"
    finally:
        assert await adapter.remove()


@pytest.mark.asyncio
async def test_unified_archive_reports_invalid_source_before_opening_transaction():
    from autoeval.reporting.unified_outputs import InvalidUnifiedOutput, archive_output

    with pytest.raises(InvalidUnifiedOutput):
        await archive_output(None, None, uuid4(), "fixture", b"{}", {"GPQA": ["case-1"]}, "GPQA")


@pytest.mark.asyncio
async def test_unified_archive_can_retry_after_stored_evidence_read_failure(monkeypatch):
    import hashlib
    from contextlib import asynccontextmanager
    from unittest.mock import AsyncMock, Mock

    from autoeval.reporting import unified_outputs

    raw = b"fixture"
    expected = {"GPQA": ["case-1"]}
    summary = {"validity": "complete"}
    existing = SimpleNamespace(
        sha256=hashlib.sha256(raw).hexdigest(),
        payload={"expected": expected, "summary": summary},
    )
    read = Mock(side_effect=[ValueError("Stored evidence checksum mismatch"), raw])

    @asynccontextmanager
    async def transaction():
        yield

    def sessions():
        @asynccontextmanager
        async def connect():
            yield SimpleNamespace(
                begin=transaction, scalar=AsyncMock(side_effect=[object(), existing])
            )

        return connect()

    monkeypatch.setattr(unified_outputs, "parse_output", Mock(return_value=([], summary)))
    monkeypatch.setattr(unified_outputs, "read_manifest", read)
    run_id = uuid4()
    with pytest.raises(ValueError, match="Stored evidence checksum mismatch") as exc:
        await unified_outputs.archive_output(sessions, None, run_id, "fixture", raw, expected)
    assert not isinstance(exc.value, unified_outputs.InvalidUnifiedOutput)
    assert (
        await unified_outputs.archive_output(sessions, None, run_id, "fixture", raw, expected)
        == summary
    )
    assert read.call_count == 2


def test_ssh_pool_selects_first_compatible_node_within_configured_scope(monkeypatch):
    from autoeval.planning import planning_transport

    first, second, third = (uuid4() for _ in range(3))
    template = {"revision": "fixed"}
    monkeypatch.setattr(
        planning_transport,
        "execution_template",
        lambda _, node, task: None if node == str(first) else template,
    )
    select = planning_transport.select_execution_template

    assert select(None, [first, second, third], None, {}) == (str(second), template)
    assert select(None, [first, second, third], [str(third)], {}) == (str(third), template)
    assert select(None, [first], [str(third)], {}) is None


def test_preflight_identity_changes_when_same_template_moves_to_another_node():
    from copy import deepcopy

    from autoeval.evaluation.inputs import selection_identity

    original = {
        "tasks": [
            {
                "task_id": "GPQA",
                "dataset": "GPQA",
                "compilation_id": str(uuid4()),
                "manifest_id": str(uuid4()),
                "assigned_resource_kind": "customer_ssh",
                "assigned_resource_id": str(uuid4()),
                "execution_template": {"revision": "fixed"},
            }
        ]
    }
    reassigned = deepcopy(original)
    reassigned["tasks"][0]["assigned_resource_id"] = str(uuid4())
    assert selection_identity(reassigned) != selection_identity(original)

    updated = deepcopy(original)
    updated["tasks"][0]["execution_template"]["readonly_mounts"] = ["/new-dataset"]
    assert selection_identity(updated) != selection_identity(original)


@pytest.mark.asyncio
async def test_harbor_container_waits_for_private_daemon(monkeypatch):
    from unittest.mock import Mock

    adapter = object.__new__(IsolatedPlanningContainer)
    adapter.template = {"family": "harbor"}
    adapter._ensure = Mock(return_value="owned-container")
    adapter.command = Mock(side_effect=RuntimeError("Private daemon unavailable"))
    with pytest.raises(RuntimeError, match="Harbor private Docker daemon is unavailable") as exc:
        await adapter.ensure()
    assert exc.value.container_id == "owned-container"
    command = adapter.command.call_args.args[0]
    assert command[:4] == ["exec", "owned-container", "python3", "-c"]
    assert "unix:///tmp/autoeval-docker.sock" in command[4]


def test_readonly_mount_accepts_explicit_host_and_container_paths():
    from autoeval.planning.planning_transport import readonly_mount_paths

    assert readonly_mount_paths("/data/benchmark") == ("/data/benchmark", "/data/benchmark")
    assert readonly_mount_paths({"source": "/host/datasets", "target": "/work/datasets"}) == (
        "/host/datasets",
        "/work/datasets",
    )
    for target in (
        "/tmp",
        "/tmp/autoeval-planning-runtime",
        "/var/lib",
        "/var/lib/autoeval-private-docker",
        "/var/lib/autoeval-private-docker/image",
        "/var/lib/docker",
        "/run/docker.sock",
    ):
        with pytest.raises(ValueError):
            readonly_mount_paths({"source": "/data", "target": target})


@pytest.mark.asyncio
async def test_harbor_preflight_blocks_daemon_without_image_import_permission(monkeypatch):
    from unittest.mock import AsyncMock, Mock

    from autoeval.planning.planning_transport import PlanningRemoteContainer

    adapter = object.__new__(IsolatedPlanningContainer)
    adapter.template = {"family": "harbor"}
    adapter.container_id = "owned-container"
    adapter.owner = str(uuid4())
    adapter.command = Mock(side_effect=RuntimeError("Remote command failed"))
    monkeypatch.setattr(
        PlanningRemoteContainer,
        "preflight",
        AsyncMock(
            return_value={
                "execution_ready": True,
                "blocking_reasons": [],
                "dataset_checks": [{"blocking_reasons": []}],
            }
        ),
    )

    result = await adapter.preflight([])
    reason = "harbor_private_daemon_image_import_failed"
    assert result["execution_ready"] is False
    assert result["blocking_reasons"] == [reason]
    assert result["dataset_checks"][0]["blocking_reasons"] == [reason]
    assert adapter.command.call_args.args[0][-1] == adapter.owner


@pytest.mark.asyncio
async def test_queued_preflight_blocks_template_drift_before_starting_ssh(monkeypatch):
    from unittest.mock import AsyncMock

    from autoeval.planning import planning_worker

    resource_id = str(uuid4())
    item = {
        "task_id": "GPQA",
        "dataset": "GPQA",
        "assigned_resource_id": resource_id,
        "execution_template": {"image_id": "old"},
        "tool": {"revision": "fixed"},
    }
    monkeypatch.setattr(planning_worker, "execution_template", lambda *_: {"image_id": "new"})
    connect = AsyncMock()
    monkeypatch.setattr(planning_worker, "isolated_transport", connect)
    result = await planning_worker.preflight_isolated_task(None, None, uuid4(), item, None)
    assert not result["execution_ready"]
    assert result["blocking_reasons"] == ["ssh_execution_template_changed"]
    assert result["dataset_checks"][0]["assigned_resource_id"] == resource_id
    connect.assert_not_awaited()
