import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from botocore.exceptions import ClientError, EndpointConnectionError

from autoeval import leaderboards, report_integrity


@pytest.mark.parametrize(
    "problem,expected",
    [
        (None, "verified"),
        ("missing", "missing"),
        ("network", "unavailable"),
        ("checksum", "invalid"),
        ("identity", "invalid"),
        ("summary", "invalid"),
    ],
)
async def test_report_integrity_fails_closed_without_rewriting_history(
    monkeypatch, problem, expected
):
    run = SimpleNamespace(id=uuid.uuid4())
    snapshot = SimpleNamespace(sha256="a" * 64)
    report = SimpleNamespace(
        snapshot_sha256=snapshot.sha256,
        execution_origin="simulation",
        summary={"accuracy": 37},
        validity="complete",
    )
    body = {
        "schema_version": "gpqa-report.v1",
        "run_id": str(run.id),
        "snapshot_sha256": snapshot.sha256,
        "execution_origin": "simulation",
        "summary": report.summary.copy(),
        "validity": "complete",
    }

    def read(*args):
        if problem == "missing":
            raise ClientError({"Error": {"Code": "NoSuchKey"}}, "GetObject")
        if problem == "network":
            raise EndpointConnectionError(endpoint_url="http://fixture")
        if problem == "checksum":
            raise ValueError("checksum mismatch")
        if problem == "identity":
            body["run_id"] = str(uuid.uuid4())
        if problem == "summary":
            body["summary"] = {"accuracy": 100}
        return body

    monkeypatch.setattr(report_integrity, "read_manifest", read)
    assert await report_integrity.report_evidence_status(None, report, run, snapshot) == expected
    assert report.validity == "complete" and report.summary == {"accuracy": 37}


@pytest.mark.parametrize("status", ["missing", "invalid", "unavailable"])
async def test_leaderboard_excludes_unverified_objects_even_with_complete_database_row(
    monkeypatch, status
):
    class Session:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def execute(self, statement):
            return SimpleNamespace(all=lambda: [(object(), object(), object())])

    checker = AsyncMock(return_value=status)
    rank = Mock(return_value=[])
    monkeypatch.setattr(leaderboards, "report_evidence_status", checker)
    monkeypatch.setattr(leaderboards, "rank_leaderboard", rank)
    request = SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(sessions=Session, settings=None)),
        state=SimpleNamespace(request_id="fixture"),
    )
    result = await leaderboards.leaderboard(request, dataset_key="GPQA", metric_name="accuracy")
    assert result["data"] == [] and result["excluded_unverified_reports"] == 1
    assert rank.call_args.args[0] == []


@pytest.mark.parametrize("dataset", ["MMMU-Pro", "AutomationBench"])
async def test_unimplemented_benchmark_never_relabels_gpqa_scores(dataset):
    sessions = Mock(side_effect=AssertionError("Should not query GPQA reports"))
    request = SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(sessions=sessions)),
        state=SimpleNamespace(request_id="fixture"),
    )
    result = await leaderboards.leaderboard(request, dataset_key=dataset, metric_name="accuracy")
    assert result["data"] == []
    sessions.assert_not_called()
