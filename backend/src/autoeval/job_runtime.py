"""Copied into the Linux executor. Fixed framework smoke only, never model scoring."""

import fcntl
import hashlib
import json
import os
import signal
import subprocess
import sys
import time
import uuid
from pathlib import Path

ROOT = Path("/work/autoeval-jobs")


def atomic_json(path, value):
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(value), encoding="utf-8")
    os.replace(tmp, path)


def identity(pid):
    # /proc stat's comm may contain spaces or parentheses.
    return Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[19]


def inspect_job(folder):
    if (folder / "exit.json").exists():
        return json.loads((folder / "exit.json").read_text())
    if not (folder / "job.json").exists():
        return {"state": "unknown"}
    job = json.loads((folder / "job.json").read_text())
    try:
        if job["boot_id"] != Path("/proc/sys/kernel/random/boot_id").read_text().strip():
            return {"state": "unknown"}
        if identity(job["pid"]) != job["start_time"]:
            return {"state": "unknown"}
    except OSError:
        return {"state": "unknown"}
    return {"state": "running", "pid": job["pid"]}


def child(folder):
    spec = json.loads((folder / "spec.json").read_text())

    def cancelled(signum, frame):
        atomic_json(folder / "exit.json", {"state": "cancelled"})
        raise SystemExit(0)

    signal.signal(signal.SIGTERM, cancelled)
    time.sleep(spec["duration_seconds"])
    atomic_json(
        folder / "result.json",
        {"kind": "framework_smoke", "model_called": False, "measurement": None},
    )
    atomic_json(folder / "exit.json", {"state": "succeeded"})


def main():
    action, key = sys.argv[1:3]
    uuid.UUID(key)
    if str(uuid.UUID(key)) != key:
        raise ValueError("Canonical UUID required")
    ROOT.mkdir(parents=True, exist_ok=True)
    folder = ROOT / key
    if action == "child":
        child(folder)
        return
    if action != "submit" and not folder.exists():
        print(json.dumps({"state": "unknown"}))
        return
    folder.mkdir(exist_ok=True)
    if folder.is_symlink() or folder.resolve().parent != ROOT.resolve():
        raise ValueError("Invalid job directory")
    with (folder / ".lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if action == "submit":
            spec = json.load(sys.stdin)
            if set(spec) != {"kind", "duration_seconds"} or spec["kind"] != "framework_smoke":
                raise ValueError("Unsupported job specification")
            if (
                not isinstance(spec["duration_seconds"], int)
                or not 0 <= spec["duration_seconds"] <= 30
            ):
                raise ValueError("Invalid smoke duration")
            digest = hashlib.sha256(json.dumps(spec, sort_keys=True).encode()).hexdigest()
            if (folder / "spec_hash").exists():
                if (folder / "spec_hash").read_text() != digest:
                    raise ValueError("Submission key reused with different specification")
            else:
                (folder / "spec_hash").write_text(digest)
                atomic_json(folder / "spec.json", spec)
                with (folder / "output.log").open("ab") as log:
                    proc = subprocess.Popen(
                        [sys.executable, __file__, "child", key],
                        stdin=subprocess.DEVNULL,
                        stdout=log,
                        stderr=log,
                        start_new_session=True,
                    )
                atomic_json(
                    folder / "job.json",
                    {
                        "pid": proc.pid,
                        "start_time": identity(proc.pid),
                        "boot_id": Path("/proc/sys/kernel/random/boot_id").read_text().strip(),
                    },
                )
        elif action == "cancel":
            state = inspect_job(folder)
            if state["state"] == "running":
                os.killpg(state["pid"], signal.SIGTERM)
        elif action == "collect":
            state = inspect_job(folder)
            if state["state"] == "succeeded":
                state["result"] = json.loads((folder / "result.json").read_text())
            print(json.dumps(state))
            return
        elif action != "status":
            raise ValueError("Unknown action")
        print(json.dumps(inspect_job(folder)))


if __name__ == "__main__":
    main()
