"""Real SSH persistence, simulated tool process. No model, benchmark or paid call."""

import asyncio
import hashlib
import json
import os
import shlex
import uuid

import pytest
from pydantic import SecretStr

from autoeval.config import get_settings
from autoeval.secrets import FileSecretStore
from autoeval.ssh_executor import SSHConnection, SSHExecutor
from autoeval.ssh_native import SSHNativeTransport

pytestmark = pytest.mark.skipif(
    not os.environ.get("AE_SSH_SIM_TEST"), reason="Local OpenSSH simulator required"
)

BRIDGE = b"""import json,sys,time
from pathlib import Path
request=json.load(sys.stdin)
counter=Path(__file__).with_name('counter.txt')
count=int(counter.read_text())+1 if counter.exists() else 1
counter.write_text(str(count))
time.sleep(request.get('test_delay',0))
print(json.dumps({'control_fixture':True,'model_called':False,'invocations':count}))
"""


def prepared_transport():
    settings = get_settings()
    body = json.loads((settings.secret_store_path / "ssh-simulator.json").read_text())
    reference = body.pop("credential_ref")
    connection = SSHConnection(
        **body,
        owner_id=uuid.uuid4(),
        credential=SecretStr(FileSecretStore(settings.secret_store_path).get(reference)),
    )
    control = SSHExecutor(connection)
    root = f"{control.root}/tool-fixture"
    with control.connect() as client:
        control.prepare(client)
        control.command(
            client,
            [
                "python3",
                "-c",
                "from pathlib import Path; import sys; Path(sys.argv[1]).mkdir(mode=0o700)",
                root,
            ],
        )
        with client.open_sftp() as sftp, sftp.open(root + "/bridge.py", "wb") as stream:
            stream.write(BRIDGE)
        with client.open_sftp() as sftp, sftp.open(root + "/lock.json", "wb") as stream:
            stream.write(b"{}")
    return SSHNativeTransport(
        connection, root, hashlib.sha256(BRIDGE).hexdigest(), hashlib.sha256(b"{}").hexdigest()
    )


async def terminal_result(transport, key):
    for _ in range(60):
        state = await transport.lookup_request(key)
        if state["state"] == "succeeded":
            return await transport.collect_request(key)
        await asyncio.sleep(0.1)
    raise AssertionError("Native control fixture did not finish")


async def test_lost_ssh_ack_is_recovered_without_reexecuting_or_persisting_secret():
    transport = prepared_transport()
    key = str(uuid.uuid4())
    secret = "fixture-secret-" + uuid.uuid4().hex
    payload = {"operation": "infer_gpqa_smoke", "test_delay": 1, "api_key": secret}
    # Real SSH channel: send the request but close it without reading its ACK.
    client = transport.control.connect()
    try:
        transport.control.prepare(client)
        stdin, _, _ = client.exec_command(
            shlex.join(transport._native_command("submit", key)), timeout=15
        )
        stdin.write(json.dumps(payload))
        stdin.flush()
        stdin.channel.shutdown_write()
        for _ in range(40):
            state = await transport.lookup_request(key)
            if state["state"] != "unknown":
                break
            await asyncio.sleep(0.05)
        assert state["state"] in {"running", "succeeded"}
    finally:
        client.close()
    recovered = SSHNativeTransport(
        transport.control.connection,
        transport.tool_root,
        transport.bridge_sha256,
        transport.lock_sha256,
    )
    result = await terminal_result(recovered, key)
    assert result["result"] == {"control_fixture": True, "model_called": False, "invocations": 1}
    await recovered.submit_request({**payload, "api_key": "rotated-fixture-secret"}, key)
    assert (await recovered.collect_request(key))["result"]["invocations"] == 1
    with recovered.control.connect() as client, client.open_sftp() as sftp:
        for name in sftp.listdir(f"{recovered.root}/jobs/{key}"):
            with sftp.open(f"{recovered.root}/jobs/{key}/{name}", "rb") as stream:
                assert secret.encode() not in stream.read(), (
                    "Secret must remain only in pipes/memory"
                )


async def test_native_key_conflict_and_result_corruption_do_not_trigger_new_execution():
    transport = prepared_transport()
    key = str(uuid.uuid4())
    payload = {"operation": "infer_gpqa_smoke", "api_key": "fixture-only"}
    result = await transport.request(payload, key)
    assert result["model_called"] is False
    with pytest.raises(RuntimeError):
        await transport.submit_request({**payload, "test_delay": 1}, key)
    with pytest.raises(ValueError, match="different request"):
        await transport.collect_request(key, {**payload, "test_delay": 1})
    path = f"{transport.root}/jobs/{key}/result.json"
    with (
        transport.control.connect() as client,
        client.open_sftp() as sftp,
        sftp.open(path, "wb") as stream,
    ):
        stream.write(b'{"tampered":true}')
    with pytest.raises(ValueError, match="checksum"):
        await transport.collect_request(key)


@pytest.mark.parametrize("changed_field", ["bridge_sha256", "lock_sha256"])
async def test_unapproved_bridge_never_executes_and_leaves_unknown_outcome(changed_field):
    transport = prepared_transport()
    setattr(transport, changed_field, "0" * 64)
    key = str(uuid.uuid4())
    await transport.submit_request(
        {"operation": "infer_gpqa_smoke", "api_key": "fixture-only"}, key
    )
    for _ in range(40):
        state = await transport.lookup_request(key)
        if state.get("error_code"):
            break
        await asyncio.sleep(0.1)
    assert state["state"] == "unknown"
    assert state["error_code"] == "NATIVE_OUTCOME_UNCONFIRMED"
    with pytest.raises(RuntimeError, match="unconfirmed"):
        await transport.request({"operation": "infer_gpqa_smoke", "api_key": "fixture-only"}, key)


async def test_killed_remote_process_is_unknown_and_never_automatically_restarted():
    transport = prepared_transport()
    key = str(uuid.uuid4())
    payload = {"operation": "infer_gpqa_smoke", "test_delay": 10, "api_key": "fixture-only"}
    await transport.submit_request(payload, key)
    with transport.control.connect() as client, client.open_sftp() as sftp:
        with sftp.open(f"{transport.root}/jobs/{key}/job.json", "rb") as stream:
            job = json.loads(stream.read())
        transport.control.command(
            client,
            [
                "python3",
                "-c",
                "import os,signal,sys; os.killpg(int(sys.argv[1]),signal.SIGKILL)",
                str(job["pid"]),
            ],
        )
    for _ in range(40):
        observed = await transport.lookup_request(key)
        if observed["state"] == "unknown":
            break
        await asyncio.sleep(0.1)
    assert observed["state"] == "unknown"
    with pytest.raises(RuntimeError, match="unconfirmed"):
        await transport.request(payload, key)
