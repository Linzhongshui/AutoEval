import asyncio
import os
import subprocess
import uuid

import pytest

from autoeval.config import get_settings
from autoeval.docker_executor import DockerExecutor
from autoeval.resources import inspect_executor

pytestmark = pytest.mark.skipif(
    not os.environ.get("AE_DOCKER_TEST"), reason="Docker executor required"
)


async def executor():
    executable = get_settings().docker_executable
    info = await asyncio.to_thread(inspect_executor, executable, "autoeval-demo-executor-1")
    return DockerExecutor(executable, info["container_id"], info["image_id"])


async def test_actual_docker_submit_dedup_and_collect():
    adapter = await executor()
    key = str(uuid.uuid4())
    spec = {"kind": "framework_smoke", "duration_seconds": 1}
    first = await adapter.submit(spec, key)
    second = await adapter.submit(spec, key)
    assert first == second
    for _ in range(20):
        if (await adapter.status(first)).state == "succeeded":
            break
        await asyncio.sleep(0.2)
    result = await adapter.collect(first)
    assert result["state"] == "succeeded"
    assert result["result"]["model_called"] is False
    assert result["result"]["measurement"] is None


async def test_actual_docker_cancel_and_unknown_key():
    adapter = await executor()
    unknown_key = str(uuid.uuid4())
    unknown_job = await adapter.lookup(unknown_key)
    assert unknown_job.state == "unknown"
    assert await adapter.cleanup(unknown_job.job) == {"state": "unknown", "cleaned": False}
    assert (await adapter.lookup(unknown_key)).state == "unknown"
    job = await adapter.submit(
        {"kind": "framework_smoke", "duration_seconds": 30}, str(uuid.uuid4())
    )
    await asyncio.sleep(0.2)
    assert (await adapter.cleanup(job))["state"] == "running"
    assert (await adapter.status(job)).state == "running"
    await adapter.cancel(job, "cancel-once")
    for _ in range(20):
        if (await adapter.status(job)).state == "cancelled":
            break
        await asyncio.sleep(0.2)
    else:
        pytest.fail("Remote cancellation was not confirmed")
    assert await adapter.cleanup(job) == {
        "state": "cleaned", "observed_state": "cancelled", "cleaned": True,
    }
    assert await adapter.cleanup(job) == {"state": "cleaned", "cleaned": True}
    assert (await adapter.status(job)).state == "cleaned"
    with pytest.raises(subprocess.CalledProcessError):
        await adapter.submit({"kind": "framework_smoke", "duration_seconds": 0}, job.submission_key)


async def test_interrupted_cleanup_is_not_cleaned_and_can_resume():
    adapter = await executor()
    job = await adapter.submit(
        {"kind": "framework_smoke", "duration_seconds": 0}, str(uuid.uuid4())
    )
    for _ in range(20):
        if (await adapter.status(job)).state == "succeeded":
            break
        await asyncio.sleep(0.2)
    else:
        pytest.fail("Remote execution did not succeed")
    fault_injection = """
import importlib.util
import sys
from pathlib import Path
from unittest.mock import patch

spec = importlib.util.spec_from_file_location("runtime_under_test", sys.argv[1])
runtime = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runtime)
key = sys.argv[2]
sys.argv = ["job_runtime.py", "cleanup", key]
original_unlink = Path.unlink
calls = 0

def interrupted_unlink(path):
    global calls
    calls += 1
    if calls == 2:
        raise OSError("injected cleanup interruption")
    return original_unlink(path)

try:
    with patch("pathlib.Path.unlink", new=interrupted_unlink):
        runtime.main()
except OSError:
    pass
state = runtime.inspect_job(runtime.ROOT / key)
assert state["state"] == "unknown", state
assert state["cleanup_pending"] is True, state
runtime.main()
"""
    await asyncio.to_thread(
        adapter.command,
        [
            "exec",
            adapter.container_id,
            "python",
            "-c",
            fault_injection,
            adapter.remote_dir + "/job_runtime.py",
            job.submission_key,
        ],
    )
    assert (await adapter.status(job)).state == "cleaned"
