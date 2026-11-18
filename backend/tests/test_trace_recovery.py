import hashlib
import io
import json
import tarfile
import uuid

import pytest

from autoeval.reporting.trace_recovery import NativeTraceBundle


def make_bundle(path, problem=None):
    rid = uuid.uuid4()
    result = {
        "id": "session",
        "trial_name": "trial",
        "task_name": "automationbench/a",
        "finished_at": "2026-11-18T00:00:00Z",
    }
    files = {
        "result.json": json.dumps(result).encode(),
        "verifier/reward.json": b'{"accuracy":1}',
        "agent/trajectory.json": json.dumps(
            {"session_id": "session", "steps": [{"step_id": 1}]}
        ).encode(),
    }
    manifest = {
        "schema_version": "native-traces.v1",
        "run_id": str(rid),
        "trials": [
            {
                "trial_name": "trial",
                "task_name": result["task_name"],
                "finished_at": result["finished_at"],
                "files": {
                    k: {"size": len(v), "sha256": hashlib.sha256(v).hexdigest()}
                    for k, v in files.items()
                },
            }
        ],
    }
    if problem == "hash":
        manifest["trials"][0]["files"]["agent/trajectory.json"]["sha256"] = "0" * 64
    if problem == "session":
        files["agent/trajectory.json"] = b'{"session_id":"other","steps":[1]}'
        v = files["agent/trajectory.json"]
        manifest["trials"][0]["files"]["agent/trajectory.json"] = {
            "size": len(v),
            "sha256": hashlib.sha256(v).hexdigest(),
        }
    with tarfile.open(path, "w") as tar:
        for relative, raw in files.items():
            info = tarfile.TarInfo("trial/" + relative)
            info.size = len(raw)
            tar.addfile(info, io.BytesIO(raw))
        raw = json.dumps(manifest).encode()
        info = tarfile.TarInfo("manifest.json")
        info.size = len(raw)
        tar.addfile(info, io.BytesIO(raw))
        if problem == "path":
            info = tarfile.TarInfo("../escape")
            info.size = 1
            tar.addfile(info, io.BytesIO(b"x"))
        if problem == "symlink":
            info = tarfile.TarInfo("trial/link")
            info.type = tarfile.SYMTYPE
            info.linkname = "/etc/passwd"
            tar.addfile(info)
    return rid


def test_verified_native_trace_bundle(tmp_path):
    p = tmp_path / "native.tar"
    rid = make_bundle(p)
    bundle = NativeTraceBundle(p, rid)
    try:
        artifact = bundle.read(bundle.trials[0])
        assert artifact["trial_name"] == "trial"
        assert "agent/trajectory.json" in artifact["files"]
    finally:
        bundle.close()


@pytest.mark.parametrize("problem", ["hash", "session", "path", "symlink", "run"])
def test_native_trace_bundle_fails_closed(tmp_path, problem):
    p = tmp_path / "native.tar"
    rid = make_bundle(p, problem)
    if problem == "run":
        rid = uuid.uuid4()
    with pytest.raises(ValueError):
        bundle = NativeTraceBundle(p, rid)
        try:
            bundle.read(bundle.trials[0])
        finally:
            bundle.close()


@pytest.mark.parametrize("identity_matches", [True, False])
async def test_recovered_case_reuses_original_trace_identity(monkeypatch, identity_matches):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock, MagicMock

    from fastapi import HTTPException

    from autoeval.reporting import case_history

    rid, rev, attempt = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    body = {
        "schema_version": 1,
        "tool": "ais_bench",
        "subcommand": "harbor_agent",
        "case_count": 1,
        "cases": [
            {
                "dataset": "AutomationBench",
                "case_id": "a",
                "attempt": 1,
                "status": "success",
                "score": 1,
            }
        ],
    }
    row = SimpleNamespace(
        id=rev,
        run_id=rid,
        dataset_key="AutomationBench",
        parent_collection_id=uuid.uuid4(),
        provenance={"parent_sha256": "a" * 64},
        object_key="revision",
        created_at=__import__("datetime").datetime.now(),
    )
    parent = SimpleNamespace(
        sha256="a" * 64, payload={"expected": {"AutomationBench": ["a"]}}, object_key="parent"
    )
    original = SimpleNamespace(
        id=attempt, sample_id="a" if identity_matches else "other", attempt_no=1
    )
    trace = SimpleNamespace(
        attempt_id=attempt,
        status="succeeded",
        langfuse_project="project",
        trace_id="1" * 32,
        error_code=None,
        content_mode="full",
    )
    db = SimpleNamespace(
        get=AsyncMock(side_effect=[row, parent]),
        scalars=AsyncMock(side_effect=[[original], [trace]]),
    )
    context = MagicMock()
    context.__aenter__.return_value = db
    settings = SimpleNamespace(langfuse_browser_url="https://traces.example")
    request = SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(sessions=lambda: context, settings=settings)),
        state=SimpleNamespace(request_id="test"),
    )
    monkeypatch.setattr(case_history, "read_manifest", lambda *args: body)
    if not identity_matches:
        with pytest.raises(HTTPException) as exc:
            await case_history.recovered_cases(rid, rev, request)
        assert exc.value.status_code == 503
        return
    result = await case_history.recovered_cases(rid, rev, request)
    case = result["data"][0]
    assert case["original_attempt_id"] == str(attempt)
    assert case["trace_status"] == "succeeded" and case["trace_content_mode"] == "full"
    assert case["trace_url"] == "https://traces.example/project/project/traces/" + "1" * 32
    assert case["tool_metadata"]["score"] == 1
