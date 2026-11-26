"""Pin debug storage to a verified Docker mount and an independent on-volume UUID."""

import asyncio
import hashlib
import json
import re
import subprocess
from pathlib import Path

from paramiko import SSHException

from autoeval_runtime import debug_files

STORAGE_ERRORS = (
    OSError,
    ValueError,
    RuntimeError,
    KeyError,
    subprocess.SubprocessError,
    SSHException,
)
ROOT = debug_files.ROOT
READER = Path(debug_files.__file__).read_text(encoding="utf-8")


def inspect_mount(adapter, container, *, writable=True):
    row = json.loads(adapter.command(["inspect", "--type", "container", container]))[0]
    mounts = row["Mounts"]
    mount = next((m for m in mounts if m["Destination"] == ROOT), None)
    if mount and mount["Type"] == "volume":
        name = mount.get("Name", "")
        # Docker assigns a random 64-hex name to anonymous volumes.
        explicit = row.get("HostConfig", {})
        if not name or (
            re.fullmatch(r"[a-f0-9]{64}", name)
            and not any(spec.startswith(name + ":") for spec in explicit.get("Binds") or [])
            and not any(spec.get("Source") == name for spec in explicit.get("Mounts") or [])
        ):
            raise ValueError("A named artifact volume is required")
    if (
        not row["State"]["Running"]
        or not mount
        or (writable and not mount["RW"])
        or mount["Type"] not in {"bind", "volume"}
        or any(m["Destination"].startswith(ROOT + "/") for m in mounts)
    ):
        raise ValueError("Missing writable artifact mount")
    identity = [mount["Type"], mount.get("Name"), mount["Source"]]
    return (
        row["Id"],
        row["Name"].lstrip("/"),
        hashlib.sha256(json.dumps(identity).encode()).hexdigest(),
    )


def read_store(adapter, payload):
    return json.loads(
        adapter.command(
            ["exec", "-i", adapter.container_id, "python3", "-I", "-c", READER],
            json.dumps(payload).encode(),
        )
    )


async def storage_preflight(adapter, snapshot):
    try:
        _, name, mount = await asyncio.to_thread(inspect_mount, adapter, adapter.container_id)
        marker = await asyncio.to_thread(read_store, adapter, {"initialize": True})
        snapshot["debug_storage"] = {"container": name, "mount": mount, "store": marker["store"]}
    except STORAGE_ERRORS:
        snapshot["execution_ready"] = False
        snapshot.setdefault("blocking_reasons", []).append(
            f"执行器 {adapter.container_id[:12]} 需要可写持久挂载 {ROOT}"
        )
    return snapshot


def verify_store(adapter, binding):
    _, _, mount = inspect_mount(adapter, adapter.container_id)
    if (
        mount != binding["mount"]
        or read_store(adapter, {"verify": True}).get("store") != binding["store"]
    ):
        raise ValueError("Executor artifact storage changed")


def browse_store(adapter, binding, request, registered=()):
    # A replacement can retain its stable name or be registered under a new name.
    candidates = dict.fromkeys([adapter.container_id, binding["container"], *registered])
    state = "unavailable"
    for container in candidates:
        try:
            actual, _, mount = inspect_mount(adapter, container, writable=False)
        except STORAGE_ERRORS:
            continue
        if mount != binding["mount"]:
            state = "wrong_storage"
            continue
        adapter.container_id = actual
        result = read_store(adapter, {**request, "store": binding["store"]})
        if result.get("state") != "wrong_storage":
            return result
        state = "wrong_storage"
    return {"state": state}
