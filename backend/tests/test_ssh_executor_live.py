"""Actual SSH/SFTP against local Docker OpenSSH; never a customer host or model."""

import asyncio
import json
import os
import uuid

import paramiko
import pytest
from pydantic import SecretStr

from autoeval.config import get_settings
from autoeval.secrets import FileSecretStore
from autoeval.ssh_executor import SSHConnection, SSHExecutor

pytestmark = pytest.mark.skipif(
    not os.environ.get("AE_SSH_SIM_TEST"), reason="Local OpenSSH simulator required"
)


def adapter():
    settings = get_settings()
    body = json.loads((settings.secret_store_path / "ssh-simulator.json").read_text())
    reference = body.pop("credential_ref")
    return SSHExecutor(
        SSHConnection(
            **body,
            owner_id=uuid.uuid4(),
            credential=SecretStr(FileSecretStore(settings.secret_store_path).get(reference)),
        )
    )


async def wait_for(executor, job, desired):
    for _ in range(40):
        observed = await executor.status(job)
        if observed.state == desired:
            return
        await asyncio.sleep(0.1)
    raise AssertionError(f"Remote state never became {desired}")


async def test_ssh_submission_deduplicates_and_collects_result_via_sftp():
    executor = adapter()
    key = str(uuid.uuid4())
    job = await executor.submit({"kind": "framework_smoke", "duration_seconds": 1}, key)
    assert await executor.submit({"kind": "framework_smoke", "duration_seconds": 1}, key) == job
    await wait_for(executor, job, "succeeded")
    result = await executor.collect(job)
    assert result["result"]["model_called"] is False
    assert result["result"]["measurement"] is None
    with pytest.raises(RuntimeError):
        await executor.submit({"kind": "framework_smoke", "duration_seconds": 2}, key)
    unknown = str(uuid.uuid4())
    assert (await executor.lookup(unknown)).state == "unknown"
    with executor.connect() as client, client.open_sftp() as sftp, pytest.raises(FileNotFoundError):
        sftp.stat(f"{executor.root}/jobs/{unknown}")


async def test_ssh_cancel_and_cleanup_preserve_unowned_files():
    executor = adapter()
    with (
        executor.connect() as client,
        client.open_sftp() as sftp,
        sftp.open("/work/customer-existing.txt", "w") as stream,
    ):
        stream.write("customer data must remain")
    job = await executor.submit(
        {"kind": "framework_smoke", "duration_seconds": 20}, str(uuid.uuid4())
    )
    await wait_for(executor, job, "running")
    await executor.cancel(job, "cancel-fixture")
    await wait_for(executor, job, "cancelled")
    assert (await executor.cleanup(job))["cleaned"] is True
    assert (await executor.cleanup(job))["cleaned"] is True
    with (
        executor.connect() as client,
        client.open_sftp() as sftp,
        sftp.open("/work/customer-existing.txt", "r") as stream,
    ):
        assert stream.read() == b"customer data must remain"


async def test_ssh_fingerprint_mismatch_rejects_before_authentication():
    executor = adapter()
    executor.connection.fingerprint = "SHA256:" + "A" * 43
    with pytest.raises(paramiko.SSHException, match="approved"):
        executor.connect()
