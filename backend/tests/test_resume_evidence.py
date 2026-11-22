from types import SimpleNamespace

import pytest
from botocore.exceptions import ClientError

from autoeval.evaluation.resume_evidence import (
    AttemptObservation,
    classify_sample,
    observe_archived_attempt,
)


@pytest.mark.parametrize(
    ("attempts", "expected", "reconciled", "category"),
    [
        ([AttemptObservation("1", "succeeded", "verified", 0)], 1, True, "reusable"),
        ([AttemptObservation("1", "succeeded", "verified", 0)], 2, True, "remaining"),
        ([AttemptObservation("1", "succeeded", "lost", None)], 1, True, "evidence_lost"),
        ([AttemptObservation("1", "succeeded", "unavailable", None)], 1, True, "unknown"),
        ([AttemptObservation("1", "started", "unavailable", None)], 1, True, "unknown"),
        ([], 1, False, "unknown"),
        ([], 1, True, "remaining"),
    ],
)
def test_case_disposition(attempts, expected, reconciled, category):
    assert (
        classify_sample(
            attempts, expected_attempts=expected, dispatch_reconciled=reconciled
        ).category
        == category
    )


@pytest.mark.parametrize(
    ("error", "sample_id", "category"),
    [
        ("NoSuchKey", "q0", "evidence_lost"),
        ("AccessDenied", "q0", "unknown"),
        ("NoSuchBucket", "q0", "unknown"),
        (None, "foreign-sample", "unknown"),
        (None, "q0", "reusable"),
    ],
)
async def test_archived_evidence_disposition(monkeypatch, error, sample_id, category):
    record = SimpleNamespace(
        id="attempt-id", state="succeeded", dataset_key="GPQA", sample_id="q0", attempt_no=1
    )

    def read(_settings, _record):
        if error:
            raise ClientError({"Error": {"Code": error}}, "GetObject")
        return {
            "schema_version": "unified-case.v1",
            "dataset_key": "GPQA",
            "sample_id": sample_id,
            "attempt_no": 1,
            "status": "success",
            "score": 0,
        }

    monkeypatch.setattr("autoeval.evaluation.resume_evidence.read_manifest", read)
    observed = await observe_archived_attempt(None, record)
    assert (
        classify_sample([observed], expected_attempts=1, dispatch_reconciled=True).category
        == category
    )
