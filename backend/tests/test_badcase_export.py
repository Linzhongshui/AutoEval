"""Badcase package primitives; no real database, storage or model is used."""

import csv
import io
import json
import os
import tempfile
import zipfile

import pytest
from fastapi import HTTPException

from autoeval.reporting.badcase_export import (
    ExportInput,
    Writer,
    add_trajectory,
    case_trajectory,
    csv_bytes,
    inference_view,
    redact,
    redact_text,
    safe_name,
    safe_trajectory_path,
    selected_cases,
)


def sample_data():
    return {
        "datasets": [
            {
                "dataset_key": "GPQA-Diamond",
                "cases": [
                    {"sample_id": "gpqa_diamond:0", "verdict": {"band": "high"}},
                    {"sample_id": "gpqa_diamond:1", "verdict": {"band": "low"}},
                    {"sample_id": "gpqa_diamond:2", "verdict": {"band": "non_badcase"}},
                ],
            }
        ]
    }


def test_selected_cases_scopes():
    data = sample_data()
    high = selected_cases(data, ExportInput(scope="high"))
    assert [case["sample_id"] for _, case in high] == ["gpqa_diamond:0"]
    suspicious = selected_cases(data, ExportInput(scope="suspicious"))
    assert [case["sample_id"] for _, case in suspicious] == [
        "gpqa_diamond:0",
        "gpqa_diamond:1",
    ]
    chosen = selected_cases(
        data, ExportInput(scope="selected", sample_ids=["gpqa_diamond:1"])
    )
    assert [case["sample_id"] for _, case in chosen] == ["gpqa_diamond:1"]
    with pytest.raises(HTTPException):
        selected_cases(
            data, ExportInput(scope="selected", sample_ids=["missing"])
        )


def test_all_scope_exports_beyond_selected_limit():
    data = {
        "datasets": [
            {
                "dataset_key": "GPQA-Diamond",
                "cases": [
                    {"sample_id": f"gpqa_diamond:{index}", "verdict": {"band": "high"}}
                    for index in range(120)
                ],
            }
        ]
    }
    rows = selected_cases(data, ExportInput(scope="all"))
    assert len(rows) == 120
    high = selected_cases(data, ExportInput(scope="high"))
    assert len(high) == 120
    oversized = ExportInput.model_construct(
        scope="selected",
        sample_ids=[f"gpqa_diamond:{index}" for index in range(101)],
        dataset_key=None,
        include_traces=True,
    )
    with pytest.raises(HTTPException):
        selected_cases(data, oversized)


def test_redact_removes_credentials_and_base_url():
    value = {
        "api_key": "secret",
        "nested": {"base_url": "https://api.example", "keep": 1},
        "items": [{"password": "p", "credential_ref": "c", "score": 1}],
    }
    assert redact(value) == {"nested": {"keep": 1}, "items": [{"score": 1}]}


def test_safe_name_keeps_identity_readable():
    assert safe_name("gpqa_diamond:0") == "gpqa_diamond_0"
    assert safe_name("a b/c") == "a_b_c"
    assert safe_name("::") == "case"


def test_inference_view_includes_prompt_and_model_response():
    view = inference_view(
        sample_id="gpqa_diamond:0",
        dataset_key="GPQA-Diamond",
        run_id="run",
        report_id="report",
        model="deepseek-flash",
        attempt_no=1,
        evidence={
            "prompt": "Question",
            "response": "Answer: A",
            "messages": [{"role": "HUMAN", "prompt": "Question"}],
            "usage": {"input_tokens": 10, "output_tokens": 20},
        },
        case={"raw": {"score": 1.0, "status": "success"}},
    )
    assert view["available"] is True
    assert view["prompt"] == "Question"
    assert view["response"] == "Answer: A"
    assert view["prediction"] == "Answer: A"
    assert view["output"] == "Answer: A"
    assert "case_evidence" in view["sources"]
    assert view["usage"]["output_tokens"] == 20


def test_inference_view_falls_back_to_unified_raw_prompt_and_prediction():
    view = inference_view(
        sample_id="gpqa_diamond:0",
        dataset_key="GPQA-Diamond",
        run_id="run",
        report_id="report",
        model="deepseek-flash",
        attempt_no=1,
        evidence={"available": False},
        case={
            "raw": {
                "origin_prompt": [{"role": "HUMAN", "prompt": "Question"}],
                "prediction": "Answer: B",
                "input_tokens": 10,
                "output_tokens": 20,
            }
        },
    )
    assert view["available"] is True
    assert view["response"] == "Answer: B"
    assert "unified_raw.origin_prompt" in view["sources"]


def test_trajectory_files_are_sanitized_redacted_and_indexed():
    trajectory = json.dumps({"steps": [], "api_key": "secret"})
    case = {
        "raw": {
            "harbor_artifact": {
                "trial_name": "trial-1",
                "files": {
                    "agent/trajectory.json": trajectory,
                    "../escape.json": "{}",
                },
            }
        }
    }
    artifact, files = case_trajectory(case)
    assert artifact["trial_name"] == "trial-1"
    assert set(files) == {"agent/trajectory.json", "../escape.json"}
    assert safe_trajectory_path("agent/trajectory.json") == "agent/trajectory.json"
    assert safe_trajectory_path("../escape.json") is None
    assert "api_key" not in redact_text(trajectory)

    with tempfile.NamedTemporaryFile(delete=False, suffix=".zip") as handle:
        path = handle.name
    try:
        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
            writer = Writer(archive)
            add_trajectory(writer, "cases/x/current", case, None, "current")
            names = {entry["path"] for entry in writer.files}
            assert "cases/x/current/trajectory/agent/trajectory.json" in names
            assert "cases/x/current/trajectory/manifest.json" in names
            assert not any("../" in name for name in names)
        with zipfile.ZipFile(path) as archive:
            content = archive.read(
                "cases/x/current/trajectory/agent/trajectory.json"
            ).decode()
            assert "api_key" not in content
    finally:
        os.unlink(path)


def test_csv_and_writer_manifest_entries():
    raw = csv_bytes(
        [
            {
                "sample_id": "gpqa_diamond:0",
                "dataset_key": "GPQA-Diamond",
                "current_score": 0,
                "current_state": "succeeded",
                "history_n": 4,
                "history_mean": 0.75,
                "delta": -0.75,
                "suspicion": 0.3333,
                "band": "low",
                "method": "T1",
                "p_hat": 0.6667,
            }
        ]
    )
    rows = list(csv.DictReader(io.StringIO(raw.decode("utf-8-sig"))))
    assert rows[0]["band"] == "low" and rows[0]["history_n"] == "4"

    with tempfile.NamedTemporaryFile(delete=False, suffix=".zip") as handle:
        path = handle.name
    try:
        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
            writer = Writer(archive)
            writer.add_json("case.json", {"sample_id": "x"})
            writer.add("readme.md", b"hello")
            assert {entry["path"] for entry in writer.files} == {"case.json", "readme.md"}
            assert all(len(entry["sha256"]) == 64 for entry in writer.files)
        with zipfile.ZipFile(path) as archive:
            assert set(archive.namelist()) == {"case.json", "readme.md"}
    finally:
        os.unlink(path)
