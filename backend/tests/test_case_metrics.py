import copy
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from autoeval.reporting import case_metrics as m


def test_metric_view_preserves_known_zero_and_marks_missing():
    original = {"score": None, "input_tokens": 0, "output_tokens": 0, "duration_sec": 12}
    saved = copy.deepcopy(original)
    view = m.metric_view(original, {"score": 0, "input_tokens": None, "output_tokens": None})
    assert (
        view["score"] == 0
        and view["input_tokens"] is None
        and view["token_status"] == "not_collected"
    )
    assert view["duration_sec"] == 12 and original == saved
    assert (
        m.metric_view({"input_tokens": 0, "output_tokens": 5, "duration_sec": None})["input_tokens"]
        == 0
    )
    assert m.metric_view({"duration_sec": None})["duration_status"] == "not_collected"


async def test_current_metrics_uses_explicit_report_archive_without_rewriting_history(monkeypatch):
    row = SimpleNamespace(
        id=uuid.uuid4(),
        dataset_key="AutomationBench",
        sample_id="sample",
        attempt_no=1,
        sha256="old",
        tool_metadata={"score": None, "input_tokens": 0, "output_tokens": 0, "duration_sec": 237},
    )
    report = SimpleNamespace(id=uuid.uuid4(), object_key="report", sha256="report-sha")
    ref = {
        "id": str(uuid.uuid4()),
        "object_key": "archive",
        "sha256": "archive-sha",
        "kind": "recovery",
    }
    report_body = {
        "schema_version": "task-report.v2",
        "datasets": [
            {
                "dataset_key": "AutomationBench",
                "archive": ref,
                "context": {"samples": [{"sample_id": "sample"}]},
            }
        ],
    }
    raw = {
        "schema_version": 1,
        "tool": "ais_bench",
        "subcommand": "harbor_agent",
        "case_count": 1,
        "cases": [
            {
                "case_id": "sample",
                "dataset": "AutomationBench",
                "attempt": 1,
                "status": "success",
                "score": 1,
                "input_tokens": None,
                "output_tokens": None,
                "duration_sec": 237,
            }
        ],
    }
    monkeypatch.setattr(
        m,
        "read_manifest",
        lambda settings, source: report_body if source.object_key == "report" else raw,
    )
    monkeypatch.setattr(m, "report_evidence_status", AsyncMock(return_value="verified"))
    db = SimpleNamespace(
        scalar=AsyncMock(side_effect=[report, object()]), get=AsyncMock(return_value=object())
    )
    result = await m.current_metrics(db, None, uuid.uuid4(), [row])
    meta, source = result[row.id]
    assert meta["score"] == 1 and meta["input_tokens"] is None and meta["duration_sec"] == 237
    assert source["archive_id"] == ref["id"] and source["original_evidence_sha256"] == "old"
    assert row.tool_metadata["score"] is None and row.tool_metadata["input_tokens"] == 0


async def test_unverified_metrics_fail_closed(monkeypatch):
    report = SimpleNamespace(object_key="report")
    monkeypatch.setattr(m, "read_manifest", lambda *args: {"schema_version": "task-report.v2"})
    monkeypatch.setattr(m, "report_evidence_status", AsyncMock(return_value="invalid"))
    db = SimpleNamespace(
        scalar=AsyncMock(side_effect=[report, object()]), get=AsyncMock(return_value=object())
    )
    with pytest.raises(ValueError, match="verified"):
        await m.current_metrics(db, None, uuid.uuid4(), [])
