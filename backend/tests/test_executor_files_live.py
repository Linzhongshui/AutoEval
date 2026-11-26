"""Disposable executor, fixed-output tool and named volume. No model or external network."""

import asyncio
import hashlib
import os
import subprocess
import time
import uuid
from contextlib import ExitStack

import pytest

from autoeval.planning.debug_storage import ROOT, browse_store, storage_preflight
from autoeval.planning.planning_transport import PlanningDocker, PlanningRemoteContainer
from autoeval.resources import inspect_executor
from autoeval_runtime.planning_runtime import ADAPTOR_REVISION

pytestmark = pytest.mark.skipif(not os.getenv("AE_DOCKER_TEST"), reason="Requires local Docker")


def docker(*args, data=None):
    return (
        subprocess.run(["docker", *args], input=data, capture_output=True, check=True, timeout=45)
        .stdout.decode()
        .strip()
    )


TOOL = """#!/usr/bin/env python3
import json, sys, time
from pathlib import Path
params = json.loads(Path(sys.argv[2]).read_text())["params"]
output = Path(params["work_dir"])
alternate = output.parent / "outputs"
alternate.mkdir()
(alternate / "summary.native").write_text("native summary")
nested = output / "outputs" / "trial"
nested.mkdir(parents=True)
(nested / ".status").write_text("complete")
(nested / "config.json").write_text("{}")
for index in range(115):
    (nested / f"{index:03}.json").write_text("{}")
(output / "case.txt").write_text("fixed prediction")
(output / "trace.json").write_text(json.dumps({"trace": params["api_key"]}))
(output / "binary.bin").write_bytes(bytes(range(256)))
(output / "external").symlink_to("/etc/passwd")
print("first line", flush=True)
if params["fixture"] == "cancelled":
    while not Path("/tmp/fixture-continue").exists():
        time.sleep(0.1)
print("trace line\\n" * 7500, flush=True)
print("credential=" + params["api_key"], flush=True)
if params["fixture"] == "cancelled":
    time.sleep(120)
if params["fixture"] == "failed":
    sys.exit(3)
(output / "unified_result.json").write_text('{"cases": []}')
print("last line", flush=True)
"""


@pytest.mark.parametrize(
    "ssh",
    [
        False,
        pytest.param(
            True,
            marks=pytest.mark.skipif(
                not os.getenv("AE_SSH_SIM_TEST"), reason="Loopback SSH fixture requires opt-in"
            ),
        ),
    ],
)
async def test_retained_executor_files(tmp_path, ssh):
    from debug_ssh_fixture import docker_ssh_fixture

    name = "ae-debug-test-" + uuid.uuid4().hex
    volume = name + "-files"
    image = "python:3.12-slim"
    key = "fixture-sensitive-value"

    owned = {name}
    stack = ExitStack()
    connection = stack.enter_context(docker_ssh_fixture(owned)) if ssh else None

    def launch(mount):
        args = ["-v", mount + ":" + ROOT] if mount else []
        docker(
            "run",
            "-d",
            "--name",
            name,
            "--label",
            "autoeval.role=executor",
            "--network",
            "none",
            *args,
            image,
            "sleep",
            "600",
        )
        info = inspect_executor("docker", name)
        owned.add(info["container_id"])
        if connection:
            return PlanningRemoteContainer(connection, info["container_id"], info["image_id"])
        return PlanningDocker("docker", info["container_id"], info["image_id"])

    def read(adapter, binding, job, path=""):
        return browse_store(adapter, binding, {"job": job, "path": path})

    docker("volume", "create", volume)
    try:
        adapter = launch(None)
        blocked = await storage_preflight(adapter, {"execution_ready": True})
        assert not blocked["execution_ready"] and ROOT in blocked["blocking_reasons"][0]
        docker("rm", "-f", name)
        adapter = launch(volume)
        snapshot = await storage_preflight(adapter, {"execution_ready": True})
        binding = adapter.debug_storage = snapshot["debug_storage"]
        tool = tmp_path / "autoeval-adaptor"
        tool.write_bytes(TOOL.encode())
        docker("cp", str(tool), name + ":/usr/local/bin/autoeval-adaptor")
        # Isolated test image advertises the fixture distribution and tool revision.
        docker(
            "exec",
            name,
            "python",
            "-c",
            """
import json, pathlib, sysconfig, sys
p = pathlib.Path(sysconfig.get_path('purelib')) / 'autoeval_benchmark_adaptor-0.dist-info'
p.mkdir()
(p / 'METADATA').write_text('Name: autoeval-benchmark-adaptor\\nVersion: 0\\n')
(p / 'direct_url.json').write_text(json.dumps({'vcs_info': {'commit_id':sys.argv[1]}}))
git = pathlib.Path('/usr/local/bin/git')
git.write_text('#!/bin/sh\\necho fixture-revision\\n')
git.chmod(0o755)
pathlib.Path('/usr/local/bin/autoeval-adaptor').chmod(0o755)
pathlib.Path('/tmp/fixture-scorer').write_bytes(b'fixture')
""",
            ADAPTOR_REVISION,
        )
        jobs = []
        for expected in ("succeeded", "failed", "cancelled"):
            job_id = str(uuid.uuid4())
            assert read(adapter, binding, job_id)["state"] == "pending"
            spec = {
                "kind": "adaptor",
                "credential": key,
                "tool": {
                    "scorer_reference": "fixture-scorer",
                    "revision": "fixture-revision",
                    "scorer_sha256": hashlib.sha256(b"fixture").hexdigest(),
                },
                "compilation": {
                    "adaptor_revision": ADAPTOR_REVISION,
                    "config": {
                        "subcommand": "llm_accuracy",
                        "params": {"ais_bench_root": "/tmp", "fixture": expected},
                    },
                },
            }
            job = await adapter.submit(spec, job_id)
            jobs.append(job_id)
            if expected == "cancelled":
                for _ in range(50):
                    if read(adapter, binding, job_id, "output/case.txt").get("content"):
                        break
                    await asyncio.sleep(0.1)
                assert (await adapter._invoke("status", job_id))["state"] == "running"
                first = read(adapter, binding, job_id, "tool.log")
                assert "first line" in first["content"]
                docker("exec", name, "touch", "/tmp/fixture-continue")
                for _ in range(30):
                    current = read(adapter, binding, job_id, "tool.log")
                    if current["start"] > 0 and current["size"] > first["size"]:
                        break
                    await asyncio.sleep(0.1)
                else:
                    pytest.fail("Log did not grow while the job was running")
                await adapter.cancel(job, "fixture")
            deadline = time.monotonic() + 20
            while time.monotonic() < deadline:
                observed = (await adapter._invoke("status", job_id))["state"]
                if observed == expected:
                    break
                await asyncio.sleep(0.2)
            assert observed == expected
            assert (await adapter.cleanup(job))["cleaned"]
            assert (await adapter.cleanup(job))["cleaned"]
            assert key not in docker("exec", name, "cat", ROOT + "/" + job_id + "/tool.log")
            query = {"job": job_id, "path": "", "view": "outputs"}
            page = browse_store(adapter, binding, query)
            assert len(page["entries"]) == 100 and page["more"]
            rest = browse_store(adapter, binding, {**query, "offset": 100})
            assert not rest["more"]
            entries = {e["name"]: e for e in page["entries"] + rest["entries"]}
            prefix = "output/outputs/trial/"
            assert all(prefix + f"{i:03}.json" in entries for i in range(115))
            assert entries[prefix + ".status"]["metadata_only"]
            assert entries[prefix + "config.json"]["metadata_only"]
            assert entries["output/external"]["metadata_only"]
            assert "output/binary.bin" in entries
            assert "outputs/summary.native" in entries
            assert read(adapter, binding, job_id, "outputs/summary.native")["content"] == "native summary"
            body = read(adapter, binding, job_id, "output/case.txt")
            assert body["content"] == "fixed prediction"
            assert (
                read(adapter, binding, job_id, "output/trace.json")["content"]
                == '{"trace": "[REDACTED]"}'
            )
            log = read(adapter, binding, job_id, "tool.log")
            assert log["start"] > 0 and key not in log["content"] and "[REDACTED]" in log["content"]
            assert read(adapter, binding, job_id, "output/binary.bin")["state"] == "binary"
            for path in ("output/external", "output/../spec.json", "credential.json"):
                assert "content" not in read(adapter, binding, job_id, path)
            assert not any(
                e["name"] == "external" for e in read(adapter, binding, job_id, "output")["entries"]
            )
            docker("exec", name, "test", "!", "-e", "/tmp/autoeval-private-" + job_id)
        before = hashlib.sha256(
            read(adapter, binding, jobs[0], "output/case.txt")["content"].encode()
        ).digest()

        def recreate(other=False):
            docker("rm", "-f", name)
            launch(volume + "-other" if other else volume)

        if os.getenv("AE_BROWSER_URL") and os.getenv("AE_INFRA_TEST"):
            from browser_checks.executor_files_acceptance import verify_task_page

            await verify_task_page(
                tmp_path,
                binding,
                adapter.container_id,
                adapter.image_id,
                jobs,
                key,
                recreate,
                connection,
            )
        else:
            recreate()
        assert (
            hashlib.sha256(
                read(adapter, binding, jobs[0], "output/case.txt")["content"].encode()
            ).digest()
            == before
        )
        # Simulate manual removal of just this test-owned job directory.
        docker(
            "exec",
            name,
            "python",
            "-c",
            "import shutil,sys;shutil.rmtree(sys.argv[1])",
            ROOT + "/" + jobs[0],
        )
        assert read(adapter, binding, jobs[0])["state"] == "removed"
        assert read(adapter, binding, jobs[1], "output/case.txt")["state"] == "text"
        docker("rm", "-f", name)
        launch(volume + "-other")
        assert read(adapter, binding, jobs[1])["state"] == "wrong_storage"
    finally:
        stack.close()
        await asyncio.to_thread(
            subprocess.run, ["docker", "rm", "-f", name], capture_output=True, check=False
        )
        await asyncio.to_thread(
            subprocess.run,
            ["docker", "volume", "rm", volume, volume + "-other"],
            capture_output=True,
            check=False,
        )
