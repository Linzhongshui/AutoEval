import asyncio
import io
import json
import shlex
import stat
import uuid
from contextlib import nullcontext
from types import SimpleNamespace

import pytest

from autoeval.evaluation.orchestration import keep_heartbeat
from autoeval.planning.planning_transport import PlanningRemoteContainer
from autoeval_runtime.planning_runtime import attach_harbor_evidence


def test_scoring_is_reserved_for_all_cases_before_trajectories(tmp_path):
    for name in ["a", "b"]:
        folder = tmp_path / name
        (folder / "verifier").mkdir(parents=True)
        (folder / "agent").mkdir()
        (folder / "result.json").write_text("{}")
        (folder / "verifier/reward.json").write_text('{"accuracy":1}')
        (folder / "agent/trajectory.json").write_text("x" * 1000)
    result = {"cases": [{"trial_dir": "a"}, {"trial_dir": "b"}]}
    attach_harbor_evidence(tmp_path, result, 1500)
    assert all("verifier/reward.json" in c["harbor_artifact"]["files"] for c in result["cases"])
    assert "agent/trajectory.json" in result["cases"][0]["harbor_artifact"]["files"]
    assert result["cases"][1]["trajectory_evidence"]["status"] == "retained_remote"
    assert (tmp_path / "b/agent/trajectory.json").exists()


def test_small_job_keeps_automatic_trace_and_never_inlines_credentials(tmp_path):
    (tmp_path / "a/agent").mkdir(parents=True)
    (tmp_path / "a/result.json").write_text("{}")
    (tmp_path / "a/agent/trajectory.json").write_text("trajectory")
    result = {"cases": [{"trial_dir": "a"}]}
    attach_harbor_evidence(tmp_path, result, 10000)
    assert result["cases"][0]["harbor_artifact"]["files"]["agent/trajectory.json"] == "trajectory"
    attach_harbor_evidence(tmp_path, result, 10000, "trajectory")
    assert "agent/trajectory.json" not in result["cases"][0]["harbor_artifact"]["files"]
    with pytest.raises(ValueError, match="budget"):
        attach_harbor_evidence(tmp_path, result, 1)


@pytest.mark.parametrize("oversize", [False, True])
async def test_remote_collect_is_bounded_and_shell_quoted(oversize):
    adapter = PlanningRemoteContainer.__new__(PlanningRemoteContainer)
    adapter.container_id = "c" * 64
    adapter.remote_dir = "/runtime with space/$(unsafe)"
    raw = json.dumps({"value": "x" * (17 * 1024 * 1024 if oversize else 2 * 1024 * 1024)}).encode()
    paths = []
    removed = []
    commands = []
    sftp = SimpleNamespace(
        lstat=lambda p: SimpleNamespace(st_mode=stat.S_IFREG, st_size=len(raw)),
        open=lambda p, mode: io.BytesIO(raw),
        remove=removed.append,
    )
    client = SimpleNamespace(open_sftp=lambda: nullcontext(sftp))

    def command(client, args, payload=None):
        if args[:2] == ["docker", "exec"]:
            return "[]"
        assert args[:2] == ["sh", "-c"]
        commands.append(args[2])
        assert args[2].startswith("umask 077; set -C; ")
        pieces = shlex.split(args[2].split("; ", 2)[2])
        shell = pieces.index("sh")
        assert pieces[shell + 2] == 'export PYTHONPATH="$1${PYTHONPATH:+:$PYTHONPATH}"; shift; exec "$@"'
        assert pieces[shell + 4] == adapter.remote_dir + "/deps"
        paths.append(pieces[-1])
        return ""

    adapter.control = SimpleNamespace(connect=lambda: nullcontext(client), command=command)
    job = SimpleNamespace(submission_key=str(uuid.uuid4()))
    if oversize:
        with pytest.raises(ValueError, match="large"):
            await adapter.collect(job)
    else:
        assert len((await adapter.collect(job))["value"]) == 2 * 1024 * 1024
    assert removed == paths and len(paths) == 1


async def test_archive_heartbeat_runs_and_stops_after_completion():
    count = 0

    def beat():
        nonlocal count
        count += 1

    await keep_heartbeat(beat, asyncio.sleep(0.03), interval_seconds=0.005)
    assert count > 0
    done = count
    await asyncio.sleep(0.02)
    assert count == done


async def test_heartbeat_failure_is_not_silently_discarded():
    def beat():
        raise RuntimeError("heartbeat failed")

    with pytest.raises(RuntimeError, match="heartbeat failed"):
        await keep_heartbeat(beat, asyncio.sleep(0.02), interval_seconds=0.005)
