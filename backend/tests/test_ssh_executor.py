import base64
import hashlib
import io
import uuid

import paramiko
import pytest
from pydantic import SecretStr, ValidationError

from autoeval.secrets import FileSecretStore
from autoeval.ssh_executor import PinnedHostKey, SSHConnection, SSHExecutor, load_private_key


def connection(**updates):
    return SSHConnection(
        **{
            "host": "127.0.0.1",
            "port": 2222,
            "username": "autoeval",
            "fingerprint": "SHA256:" + "A" * 43,
            "workdir": "/work",
            "owner_id": uuid.uuid4(),
            "credential": SecretStr("fixture-only"),
            "auth_kind": "password",
            **updates,
        }
    )


def test_pinned_host_key_accepts_only_approved_sha256():
    key = paramiko.RSAKey.generate(2048)
    fingerprint = "SHA256:" + base64.b64encode(
        hashlib.sha256(key.asbytes()).digest()
    ).decode().rstrip("=")
    client = paramiko.SSHClient()
    PinnedHostKey(fingerprint).missing_host_key(client, "fixture", key)
    assert not client.get_host_keys(), "No automatic trust-on-first-use persistence"
    with pytest.raises(paramiko.SSHException, match="approved"):
        PinnedHostKey("SHA256:" + "A" * 43).missing_host_key(client, "fixture", key)


@pytest.mark.parametrize(
    "path", ["/", "//", "../work", "/work/../data", "/work//data", "/work\nother"]
)
def test_rejects_noncanonical_or_root_execution_directory(path):
    with pytest.raises(ValidationError):
        connection(workdir=path)


def test_private_key_store_requires_explicit_multiline_and_never_exposes_secret(tmp_path):
    key = paramiko.RSAKey.generate(2048)
    output = io.StringIO()
    key.write_private_key(output)
    value = output.getvalue()
    store = FileSecretStore(tmp_path)
    with pytest.raises(ValueError):
        store.put(value)
    reference = store.put(value, allow_multiline=True)
    assert load_private_key(store.get(reference)).asbytes() == key.asbytes()
    assert value not in repr(connection(credential=SecretStr(value)))


async def test_ssh_executor_refuses_arbitrary_commands_and_invalid_job_specs():
    adapter = SSHExecutor(connection())
    with pytest.raises(ValueError):
        await adapter.submit({"command": "anything"}, str(uuid.uuid4()))
    with pytest.raises(ValueError):
        await adapter.submit(
            {"kind": "framework_smoke", "duration_seconds": True}, str(uuid.uuid4())
        )
