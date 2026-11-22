"""Copied into the Linux executor. Fixed framework smoke only, never model scoring."""

import fcntl
import hashlib
import json
import os
import re
import signal
import subprocess
import sys
import time
import uuid
from pathlib import Path

ROOT = Path(os.environ.get("AE_JOB_ROOT", "/work/autoeval-jobs"))


def atomic_json(path, value):
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(value), encoding="utf-8")
    os.replace(tmp, path)


def write_credential(path, credential):
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w") as stream:
        json.dump({"value": credential}, stream)


def cleanup_harbor_projects(folder):
    """Remove only containers and networks from this job's recorded Compose projects."""
    journal = folder / "compose-projects"
    if not journal.is_dir() or journal.is_symlink():
        return False
    owner = uuid.UUID(folder.name).hex
    project_pattern = re.compile(rf"ae-{owner}-[a-f0-9]{{16}}")

    def docker(*args):
        return subprocess.check_output(
            ["docker", *args], text=True, stderr=subprocess.DEVNULL, timeout=20
        ).strip()

    try:
        daemon = json.loads((journal / "daemon.json").read_text())["id"]
        if not daemon or docker("info", "--format", "{{.ID}}") != daemon:
            return False
        projects = sorted(path for path in journal.iterdir() if path.name != "daemon.json")
        if not projects or any(
            not project_pattern.fullmatch(path.name) or not path.is_file() or path.is_symlink()
            for path in projects
        ):
            return False
        for project in projects:
            label = f"label=com.docker.compose.project={project.name}"
            for kind in ("container", "network"):
                options = ["--all"] if kind == "container" else []
                listing = [kind, "ls", *options, "--quiet", "--no-trunc", "--filter", label]
                identifiers = docker(*listing).splitlines()
                if any(not re.fullmatch(r"[a-f0-9]{12,64}", value) for value in identifiers):
                    return False
                for identifier in identifiers:
                    flags = ["--force"] if kind == "container" else []
                    docker(kind, "rm", *flags, identifier)
                if docker(*listing):
                    return False
    except (OSError, ValueError, TypeError, KeyError, subprocess.SubprocessError):
        return False
    return True


def identity(pid):
    # /proc stat's comm may contain spaces or parentheses.
    return Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[19]


def session_still_running(session_id):
    for entry in Path("/proc").iterdir():
        if not entry.name.isdecimal():
            continue
        try:
            fields = (entry / "stat").read_text().rsplit(")", 1)[1].split()
        except (FileNotFoundError, ProcessLookupError):
            continue
        if fields[3] == str(session_id) and fields[0] not in {"Z", "X"}:
            return True
    return False


def inspect_job(folder):
    if (folder / "cleanup.json").exists():
        cleanup = json.loads((folder / "cleanup.json").read_text())
        if cleanup["state"] == "cleaned":
            return {"state": "cleaned"}
        return {"state": "unknown", "cleanup_pending": True}
    if (folder / "exit.json").exists():
        state = json.loads((folder / "exit.json").read_text())
        if state["state"] in {"failed", "cancelled"} and (
            state.get("reason") != "cancelled_before_launch"
        ):
            try:
                job = json.loads((folder / "job.json").read_text())
                boot_id = Path("/proc/sys/kernel/random/boot_id").read_text().strip()
                if job["boot_id"] == boot_id and session_still_running(job["pid"]):
                    return {"state": "running", "reason": "waiting_for_process_session_exit"}
            except (OSError, ValueError, KeyError, IndexError):
                return {"state": "unknown", "reason": "process_session_unverified"}
        return state
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
    os.umask(0o077)
    spec = json.loads((folder / "spec.json").read_text())

    def cancelled(signum, frame):
        atomic_json(folder / "exit.json", {"state": "cancelled"})
        raise SystemExit(0)

    if spec.get("kind") != "framework_smoke":

        def cancel_controlled(signum, frame):
            result_path = folder / "result.json"
            harbor = (
                spec.get("compilation", {}).get("config", {}).get("subcommand") == "harbor_agent"
            )
            try:
                if not result_path.exists() and spec.get("kind") == "adaptor":
                    from planning_runtime import (
                        attach_harbor_evidence,
                        collect_terminal_harbor_trials,
                        read_unified_result,
                        restore_accuracy_indices,
                    )

                    credential = json.loads((folder / "credential.json").read_text())["value"]
                    if not credential:
                        raise ValueError("Credential unavailable for result validation")
                    output = folder / "output"
                    captured = {}
                    try:
                        result, size = read_unified_result(output, credential)
                        restore_accuracy_indices(result, spec.get("case_contract"))
                        if harbor:
                            attach_harbor_evidence(
                                output, result, max(0, 12 * 1024 * 1024 - size), credential
                            )
                        captured["unified_result"] = result
                    except (OSError, TypeError, ValueError):
                        pass
                    if harbor and "unified_result" not in captured:
                        try:
                            trials = collect_terminal_harbor_trials(output, credential)
                            if trials:
                                captured["harbor_native_trials"] = trials
                        except (OSError, TypeError, ValueError):
                            pass
                    contract = spec.get("case_contract")
                    if contract:
                        from native_predictions import collect, selected

                        try:
                            files = collect(output, contract)
                            selected(files, contract)
                            if files and all(credential not in file["content"] for file in files):
                                captured.update(native_files=files, case_contract=contract)
                        except (OSError, TypeError, ValueError, KeyError):
                            pass
                    if captured:
                        atomic_json(result_path, captured)
            except (ImportError, OSError, ValueError, KeyError, TypeError):
                # Preserve cancellation even when the tool has not finished writing output.
                pass
            (folder / "credential.json").unlink(missing_ok=True)
            (folder / "private-config.json").unlink(missing_ok=True)
            atomic_json(folder / "exit.json", {"state": "cancelled", "cleanup_pending": harbor})
            raise SystemExit(0)

        signal.signal(signal.SIGTERM, cancel_controlled)
        try:
            from planning_runtime import controlled_failure_reason, execute
        except ImportError:
            atomic_json(
                folder / "exit.json", {"state": "failed", "reason": "runtime_import_failed"}
            )
            return
        try:
            result = execute(folder, spec)
            atomic_json(folder / "result.json", result)
            atomic_json(folder / "exit.json", {"state": "succeeded"})
        except Exception as exc:  # noqa: BLE001 -- isolate third-party errors without leaking credentials
            # Persist only allowlisted reason codes, never third-party response text.
            atomic_json(
                folder / "exit.json",
                {"state": "failed", "reason": controlled_failure_reason(spec, exc)},
            )
        return
    signal.signal(signal.SIGTERM, cancelled)
    time.sleep(spec["duration_seconds"])
    atomic_json(
        folder / "result.json",
        {"kind": "framework_smoke", "model_called": False, "measurement": None},
    )
    atomic_json(folder / "exit.json", {"state": "succeeded"})


def read_sample_dispatch(folder):
    journal = folder / "sample-dispatch"
    marker = journal / "instrumented"
    if journal.is_symlink() or marker.is_symlink() or not marker.is_file():
        return None
    spec = json.loads((folder / "spec.json").read_text())
    harbor = spec.get("harbor_dispatch_contract")
    contract = harbor or spec.get("case_contract")
    if not contract:
        return None
    entries = [path for path in journal.iterdir() if path.name != "instrumented"]
    expected = set(contract["case_ids"])
    if harbor:
        trials = []
        for path in sorted(entries):
            if path.is_symlink() or not path.is_file() or path.stat().st_size > 4096:
                return None
            raw = path.read_bytes()
            if hashlib.sha256(raw).hexdigest() != path.name:
                return None
            row = json.loads(raw)
            if row["tool_case_id"] not in expected or not row["trial_name"]:
                return None
            trials.append(row)
        return {
            "case_contract": contract,
            "dispatched": sorted({row["tool_case_id"] for row in trials}),
            "trials": trials,
        }
    if any(
        path.name not in expected or path.is_symlink() or not path.is_file() for path in entries
    ):
        return None
    return {"case_contract": contract, "dispatched": sorted(path.name for path in entries)}


def recover_accuracy_result(folder, result_path):
    result = json.loads(result_path.read_text())
    if result.get("unified_result") is not None or not result.get("native_files"):
        return result
    spec = json.loads((folder / "spec.json").read_text())
    contract = spec.get("case_contract")
    if not contract or result.get("case_contract") != contract:
        return result
    from planning_runtime import verify_tool

    try:
        revision = verify_tool(spec)
        root = Path(spec["compilation"]["config"]["params"]["ais_bench_root"]).resolve()
        script = """import contextlib, json, sys
from pathlib import Path
sys.path[:0] = sys.argv[1:3]
with contextlib.redirect_stdout(sys.stderr):
    import ais_bench
    from aisbench_native import score_archived_predictions
    from native_predictions import selected
    if not Path(ais_bench.__file__).resolve().is_relative_to(Path(sys.argv[1])):
        raise ValueError('Scorer imported outside the pinned tool root')
    source = json.load(sys.stdin)
    cases = score_archived_predictions(source['native_files'], source['case_contract'], selected)
print(json.dumps(cases))
"""
        proc = subprocess.run(
            [sys.executable, "-c", script, str(root), str(Path(__file__).resolve().parent)],
            input=json.dumps(result),
            text=True,
            capture_output=True,
            check=True,
            timeout=20,
        )
        cases = json.loads(proc.stdout)
    except (OSError, KeyError, ValueError, subprocess.SubprocessError):
        return result
    if cases:
        result["unified_result"] = {
            "schema_version": 1,
            "tool": "ais_bench",
            "subcommand": "llm_accuracy",
            "case_count": len(cases),
            "cases": cases,
            "score_source": "aisbench_native_prediction_scoring",
            "scorer_revision": revision,
            "scorer_sha256": spec["tool"]["scorer_sha256"],
        }
        atomic_json(result_path, result)
    return result


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
    if action not in {"submit", "cancel"} and not folder.exists():
        state = {"state": "unknown"}
        if action == "cleanup":
            state["cleaned"] = False
        print(json.dumps(state))
        return
    folder.mkdir(exist_ok=True)
    if folder.is_symlink() or folder.resolve().parent != ROOT.resolve():
        raise ValueError("Invalid job directory")
    with (folder / ".lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if action == "submit":
            if (folder / "cleanup.json").exists():
                raise ValueError("Cleaned submission key cannot be reused")
            if (folder / "exit.json").exists() and not (folder / "spec_hash").exists():
                raise ValueError("Cancelled submission key cannot be reused")
            spec = json.load(sys.stdin)
            credential = None
            if spec.get("kind") == "framework_smoke":
                if (
                    set(spec) != {"kind", "duration_seconds"}
                    or type(spec["duration_seconds"]) is not int
                    or not 0 <= spec["duration_seconds"] <= 30
                ):
                    raise ValueError("Invalid smoke specification")
            else:
                from planning_runtime import validate_spec

                validate_spec(spec)
                credential = spec.pop("credential")
                spec["credential"] = "runtime-only"
            digest = hashlib.sha256(json.dumps(spec, sort_keys=True).encode()).hexdigest()
            if (folder / "spec_hash").exists():
                if (folder / "spec_hash").read_text() != digest:
                    raise ValueError("Submission key reused with different specification")
            else:
                (folder / "spec_hash").write_text(digest)
                folder.chmod(0o700)
                if credential is not None:
                    secret_path = folder / "credential.json"
                    write_credential(secret_path, credential)
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
            if (
                state["state"] == "unknown"
                and not (folder / "spec_hash").exists()
                and not (folder / "job.json").exists()
                and not (folder / "cleanup.json").exists()
            ):
                atomic_json(
                    folder / "exit.json",
                    {"state": "cancelled", "reason": "cancelled_before_launch"},
                )
            elif state["state"] == "running" and "pid" in state:
                os.killpg(state["pid"], signal.SIGTERM)
        elif action == "cleanup":
            cleanup_path = folder / "cleanup.json"
            cleanup = json.loads(cleanup_path.read_text()) if cleanup_path.exists() else None
            if cleanup is not None and cleanup["state"] == "cleaned":
                print(json.dumps({"state": "cleaned", "cleaned": True}))
                return
            if cleanup is None:
                state = inspect_job(folder)
                spec_path = folder / "spec.json"
                saved_spec = json.loads(spec_path.read_text()) if spec_path.exists() else {}
                harbor = (
                    saved_spec.get("compilation", {}).get("config", {}).get("subcommand")
                    == "harbor_agent"
                )
                if (
                    harbor
                    and state["state"] in {"cancelled", "failed"}
                    and not cleanup_harbor_projects(folder)
                ):
                    print(
                        json.dumps(
                            {
                                **state,
                                "cleaned": False,
                                "cleanup_pending": True,
                                "reason": "Harbor external container ownership must be verified before reclaim",
                            }
                        )
                    )
                    return
                if state["state"] not in {"succeeded", "failed", "cancelled"}:
                    print(json.dumps({**state, "cleaned": False}))
                    return
                observed_state = state["state"]
                atomic_json(cleanup_path, {"state": "cleaning", "observed_state": observed_state})
            else:
                observed_state = cleanup["observed_state"]
            for path in folder.iterdir():
                if path.name not in {".lock", "cleanup.json"}:
                    if path.is_dir():
                        # Artifacts remain in the owned job directory; no recursive deletion.
                        continue
                    path.unlink()
            atomic_json(cleanup_path, {"state": "cleaned"})
            print(
                json.dumps(
                    {
                        "state": "cleaned",
                        "observed_state": observed_state,
                        "cleaned": True,
                    }
                )
            )
            return
        elif action in {"collect", "collect_dispatch"}:
            state = inspect_job(folder)
            result_path = folder / "result.json"
            if state["state"] in {"succeeded", "failed", "cancelled"}:
                if result_path.is_file():
                    result = recover_accuracy_result(folder, result_path)
                    if action == "collect":
                        state["result"] = result
                dispatch = read_sample_dispatch(folder)
                if dispatch is not None:
                    state["sample_dispatch"] = dispatch
            print(json.dumps(state))
            return
        elif action != "status":
            raise ValueError("Unknown action")
        print(json.dumps(inspect_job(folder)))


if __name__ == "__main__":
    main()
