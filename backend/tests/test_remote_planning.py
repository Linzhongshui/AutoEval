"""Remote calculation bundle parity and strict job contracts; no model calls."""

import json

import pytest

from autoeval.catalog.standard_inputs import digest, leaves, validate_config
from autoeval.planning.planning_transport import runtime_files
from autoeval_runtime.planning_runtime import validate_spec


async def test_queued_plan_with_expired_preflight_fails_before_submission(monkeypatch):
    from contextlib import asynccontextmanager
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from autoeval.planning import planning_worker as worker

    job = SimpleNamespace(
        kind="plan", state="pending", cancel_requested=False, payload={"throughput_profile_id": "curve"}
    )
    session = AsyncMock()
    session.get.side_effect = [job, SimpleNamespace()]

    @asynccontextmanager
    async def sessions():
        yield session

    adapter = AsyncMock()
    update = AsyncMock()
    monkeypatch.setattr(worker, "transport", AsyncMock(return_value=adapter))
    monkeypatch.setattr(worker, "current_preflight", AsyncMock(return_value=None))
    monkeypatch.setattr(worker, "set_job", update)
    await worker.execute_job(sessions, None, "queued-plan")
    update.assert_awaited_once()
    assert update.await_args.kwargs["state"] == "failed"
    assert update.await_args.kwargs["result"]["error_code"] == "plan_preflight_required"
    adapter.submit.assert_not_awaited()


def test_transports_ship_the_standalone_runtime_after_package_refactor():
    import ast
    from types import SimpleNamespace

    from autoeval.resources.docker_executor import DockerExecutor
    from autoeval.resources.ssh_executor import SSHExecutor

    adapters = (
        DockerExecutor("docker", "container", "image"),
        SSHExecutor(SimpleNamespace(workdir="/test", owner_id="test")),
    )
    for adapter in adapters:
        source = adapter.runtime.read_text(encoding="utf-8")
        tree = ast.parse(source)
        assert any(
            isinstance(node, ast.FunctionDef) and node.name == "atomic_json" for node in tree.body
        )
        assert "runpy.run_module" not in source
        assert "from autoeval" not in source


def test_standalone_contract_matches_platform_without_api_dependencies():
    files = runtime_files()
    namespace = {}
    exec(files["planning_contract.py"], namespace)  # noqa: S102 -- generated trusted source parity check
    value = {
        "tool": "ais_bench",
        "subcommand": "llm_accuracy",
        "params": {"datasets": ["fixture"], "batch_size": 2},
    }
    assert namespace["digest"](value) == digest(value)
    assert namespace["leaves"](value) == leaves(value)
    assert namespace["validate_config"](value) == validate_config(value)
    with pytest.raises(ValueError):
        namespace["validate_config"]({**value, "params": {"api_key": "fixture-secret"}})
    assert b"from autoeval.catalog.standard_inputs" not in files["planning_calculation.py"]


def test_plan_spec_has_no_arbitrary_command_or_extra_fields():
    value = {
        "kind": "planner_plan",
        "credential": "",
        "inputs": {},
        "curve": {},
        "resource": None,
        "history": [],
    }
    validate_spec(value)
    with pytest.raises(ValueError):
        validate_spec({**value, "command": "anything"})
    assert json.dumps(value).find("api_key") == -1


def test_probe_reports_real_level_boundaries_without_network(tmp_path, monkeypatch):
    from types import SimpleNamespace

    from autoeval_planner import probe

    from autoeval_runtime import planning_runtime as runtime

    (tmp_path / "credential.json").write_text('{"value":"TEST-only"}')
    monkeypatch.setattr(runtime, "installed_revision", lambda _: runtime.PLANNER_REVISION)
    monkeypatch.setattr(probe, "_run_level", lambda **_: [])
    seen = []

    def fake_probe(**kwargs):
        for level in kwargs["concurrency_levels"]:
            probe._run_level(concurrency=level)
            seen.append(json.loads((tmp_path / "progress.json").read_text()))
        return SimpleNamespace(to_dict=lambda: {"source": "TEST-only"})

    monkeypatch.setattr(probe, "run_probe", fake_probe)
    original = probe._run_level
    result = runtime.execute(
        tmp_path,
        {
            "kind": "planner_probe",
            "credential": "runtime-only",
            "options": {
                "base_url": "https://fixture.invalid",
                "model": "fixture",
                "concurrency_levels": [1, 2],
                "requests_per_level": 2,
                "prompt_tokens": 8,
                "max_tokens": 8,
            },
        },
    )
    assert [x["completed_levels"] for x in seen] == [1, 2]
    assert result["progress"]["stage"] == "archiving"
    assert result["progress"]["job_id"] == tmp_path.name
    assert probe._run_level is original
    assert not (tmp_path / "credential.json").exists()
