"""Badcase package primitives; no real database, storage or model is used."""

import csv
import io
import os
import tempfile
import zipfile

import pytest
from fastapi import HTTPException

from autoeval.reporting.badcase_export import (
    ExportInput,
    Writer,
    csv_bytes,
    redact,
    safe_name,
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
