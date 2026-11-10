"""Resolve frozen SSH transport without putting credentials into run snapshots."""

import uuid

from pydantic import SecretStr

from autoeval.secrets import FileSecretStore
from autoeval.ssh_executor import SSHConnection
from autoeval.ssh_native import SSHNativeTransport
from autoeval.ssh_resources import SSHResourceBinding


def frozen_ssh_resource(row, settings):
    if not row.native_tool_root:
        raise ValueError("SSH native tool root not registered")
    if not row.native_bridge_sha256 or not row.native_lock_sha256 or not row.native_tool_revision:
        raise ValueError(
            "SSH native tool version is not pinned; register an approved resource version"
        )
    return {
        "host": row.host,
        "port": row.port,
        "username": row.username,
        "fingerprint": row.fingerprint,
        "workdir": row.workdir,
        "auth_kind": row.auth_kind,
        "owner_id": str(row.id),
        "tool_root": row.native_tool_root,
        "bridge_sha256": row.native_bridge_sha256,
        "lock_sha256": row.native_lock_sha256,
        "tool_revision": row.native_tool_revision,
    }


async def ssh_transport(sessions, settings, frozen):
    async with sessions() as session:
        row = await session.get(SSHResourceBinding, uuid.UUID(frozen["resource_id"]))
        if row is None:
            raise ValueError("Frozen SSH resource no longer available")
        credential = FileSecretStore(settings.secret_store_path).get(row.credential_ref)
    spec = frozen["ssh"]
    connection = SSHConnection(
        **{
            k: spec[k]
            for k in ("host", "port", "username", "fingerprint", "workdir", "auth_kind", "owner_id")
        },
        credential=SecretStr(credential),
    )
    return SSHNativeTransport(
        connection, spec["tool_root"], spec["bridge_sha256"], spec["lock_sha256"]
    )
