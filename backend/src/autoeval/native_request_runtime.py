"""Short-lived remote native request wrapper. Secrets only pass through stdin pipes."""

import fcntl
import hashlib
import json
import os
import subprocess
import sys
import time
import uuid
from pathlib import Path

ROOT = Path(os.environ["AE_NATIVE_JOB_ROOT"])
TOOLS = Path(os.environ["AE_NATIVE_TOOL_ROOT"])
BRIDGE_SHA = os.environ["AE_NATIVE_BRIDGE_SHA256"]
LOCK_SHA = os.environ["AE_NATIVE_LOCK_SHA256"]


def atomic_json(path, value):
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(value), encoding="utf-8")
    os.replace(tmp, path)


def identity(pid):
    fields = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()
    if fields[0] in {"Z", "X"}:
        raise ProcessLookupError("Native worker no longer running")
    return fields[19]


def status(folder):
    if (folder / "exit.json").exists():
        return json.loads((folder / "exit.json").read_text())
    if not (folder / "job.json").exists():
        return {"state": "unknown"}
    job = json.loads((folder / "job.json").read_text())
    try:
        if job["boot_id"] != Path("/proc/sys/kernel/random/boot_id").read_text().strip() or job[
            "start_time"
        ] != identity(job["pid"]):
            return {"state": "unknown"}
    except OSError:
        return {"state": "unknown"}
    return {"state": "running"}


def child(folder, raw):
    try:
        bridge = TOOLS / "bridge.py"
        if hashlib.sha256(bridge.read_bytes()).hexdigest() != BRIDGE_SHA:
            raise ValueError("Approved bridge changed")
        if hashlib.sha256((TOOLS / "lock.json").read_bytes()).hexdigest() != LOCK_SHA:
            raise ValueError("Approved source lock changed")
        environment = {**os.environ, "PYTHONPATH": f"{TOOLS}/site-packages:{TOOLS}/source"}
        result = subprocess.run(
            [sys.executable, str(bridge), str(TOOLS / "source"), str(TOOLS / "lock.json")],
            input=raw,
            capture_output=True,
            timeout=100,
            env=environment,
            check=True,
        )
        if len(result.stdout) > 16 * 1024 * 1024:
            raise ValueError("Native output too large")
        body = json.loads(result.stdout)
        atomic_json(folder / "result.json", body)
        atomic_json(
            folder / "exit.json",
            {
                "state": "succeeded",
                "sha256": hashlib.sha256(result.stdout).hexdigest(),
                "result_sha256": hashlib.sha256((folder / "result.json").read_bytes()).hexdigest(),
                "request_sha256": (folder / "spec_hash").read_text(),
            },
        )
    except (OSError, ValueError, subprocess.SubprocessError):
        # The external service may have accepted the request. Never call it failed
        # or repeat it solely because the local transport/process was interrupted.
        atomic_json(
            folder / "exit.json", {"state": "unknown", "error_code": "NATIVE_OUTCOME_UNCONFIRMED"}
        )


def main():
    action, key = sys.argv[1:3]
    if str(uuid.UUID(key)) != key:
        raise ValueError("Canonical submission UUID required")
    ROOT.mkdir(parents=True, exist_ok=True, mode=0o700)
    if ROOT.is_symlink():
        raise ValueError("Invalid job root")
    folder = ROOT / key
    if action == "child":
        child(folder, sys.stdin.buffer.read(16 * 1024 * 1024 + 1))
        return
    if action != "submit" and not folder.exists():
        print(json.dumps({"state": "unknown"}))
        return
    folder.mkdir(exist_ok=True, mode=0o700)
    if folder.is_symlink() or folder.resolve().parent != ROOT.resolve():
        raise ValueError("Invalid native job directory")
    with (folder / ".lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if action == "submit":
            raw = sys.stdin.buffer.read(16 * 1024 * 1024 + 1)
            if len(raw) > 16 * 1024 * 1024:
                raise ValueError("Native input too large")
            payload = json.loads(raw)
            if payload.get("operation") != "infer_gpqa_smoke":
                raise ValueError("Only the approved native GPQA inference operation is supported")
            safe = {k: v for k, v in payload.items() if k != "api_key"}
            safe["tool_root"] = str(TOOLS)
            safe["bridge_sha256"] = BRIDGE_SHA
            safe["lock_sha256"] = LOCK_SHA
            digest = hashlib.sha256(json.dumps(safe, sort_keys=True).encode()).hexdigest()
            marker = folder / "spec_hash"
            if marker.exists():
                if marker.read_text() != digest:
                    raise ValueError("Submission key reused with different native input")
            else:
                marker.write_text(digest)
                proc = subprocess.Popen(
                    [sys.executable, __file__, "child", key],
                    stdin=subprocess.PIPE,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    start_new_session=True,
                )
                atomic_json(
                    folder / "job.json",
                    {
                        "pid": proc.pid,
                        "start_time": identity(proc.pid),
                        "boot_id": Path("/proc/sys/kernel/random/boot_id").read_text().strip(),
                        "created_at": time.time(),
                    },
                )
                try:
                    proc.stdin.write(raw)
                    proc.stdin.close()
                except (OSError, BrokenPipeError):
                    # Keep the marker even when the handoff is uncertain.
                    pass
        elif action == "collect":
            observed = status(folder)
            if observed["state"] == "succeeded":
                raw = (folder / "result.json").read_bytes()
                if hashlib.sha256(raw).hexdigest() != observed["result_sha256"]:
                    raise ValueError("Native evidence checksum mismatch")
                observed["result"] = json.loads(raw)
            print(json.dumps(observed))
            return
        elif action != "status":
            raise ValueError("Unsupported native lifecycle operation")
        print(json.dumps(status(folder)))


if __name__ == "__main__":
    main()
