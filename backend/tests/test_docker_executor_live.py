import asyncio
import os
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
    assert (await adapter.lookup(str(uuid.uuid4()))).state == "unknown"
    job = await adapter.submit(
        {"kind": "framework_smoke", "duration_seconds": 30}, str(uuid.uuid4())
    )
    await asyncio.sleep(0.2)
    await adapter.cancel(job, "cancel-once")
    for _ in range(20):
        if (await adapter.status(job)).state == "cancelled":
            return
        await asyncio.sleep(0.2)
    pytest.fail("Remote cancellation was not confirmed")
