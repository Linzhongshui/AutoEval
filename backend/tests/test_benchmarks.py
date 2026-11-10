import os
import uuid

import pytest
from pydantic import ValidationError
from sqlalchemy import text
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import DBAPIError
from sqlalchemy.schema import CreateTable

from autoeval.benchmarks import BenchmarkBaseline, compare_baseline
from autoeval.config import get_settings
from autoeval.db import create_database
from autoeval.import_benchmarks import BaselineConflictError, import_baselines

DATASET_KEY = "GPQA"
MANIFEST_SHA256 = "a" * 64
TOOL_REVISION = "b" * 40


def frozen_snapshot():
    return {
        "schema_version": "gpqa-run.v1",
        "manifest_sha256": MANIFEST_SHA256,
        "tool": {"revision": TOOL_REVISION},
        "parameters": {
            "output": 32,
            "concurrency": 1,
            "temperature": 0.0,
            "top_p": 1.0,
            "scope": "Lite",
        },
        "remote_model": "fixture-model",
    }


def conditions(**changes):
    values = {
        "dataset_key": DATASET_KEY,
        "manifest_sha256": MANIFEST_SHA256,
        "tool_revision": TOOL_REVISION,
        "output": 32,
        "concurrency": 1,
        "temperature": 0.0,
        "top_p": 1.0,
        "scope": "lite",
        "remote_model": "fixture-model",
    }
    values.update(changes)
    return values


def baseline(**changes):
    values = {
        "baseline_key": "fixture-baseline",
        "version": "fixture-v1",
        "dataset_key": DATASET_KEY,
        "subset_scope": "lite",
        "metric_name": "accuracy",
        "unit": "percent",
        "value": 40.0,
        "direction": "higher_is_better",
        "conditions": conditions(),
        "source_url": "https://example.invalid/fixture-baseline.json",
        "source_revision": "fixture-revision",
        "source_sha256": "c" * 64,
        "approved_by": "fixture-approver",
        "content_sha256": "d" * 64,
    }
    values.update(changes)
    return BenchmarkBaseline(**values)


def summary(**changes):
    values = {"accuracy": 42.5, "subset_scope": "lite"}
    values.update(changes)
    return values


def test_exact_match_returns_signed_accuracy_difference():
    result = compare_baseline(
        summary(), frozen_snapshot(), [baseline(conditions=conditions(output=64)), baseline()]
    )

    assert result == {
        "status": "matched",
        "baseline_key": "fixture-baseline",
        "baseline_version": "fixture-v1",
        "baseline_value": 40.0,
        "baseline_unit": "percent",
        "baseline_direction": "higher_is_better",
        "measured_value": 42.5,
        "difference": 2.5,
    }


def test_missing_baseline_never_becomes_zero_or_a_difference():
    result = compare_baseline(summary(), frozen_snapshot(), [])

    assert result["status"] == "missing"
    assert result["baseline_value"] is None
    assert result["baseline_unit"] is None
    assert result["baseline_direction"] is None
    assert result["measured_value"] is None
    assert result["difference"] is None


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("manifest_sha256", "e" * 64),
        ("tool_revision", "f" * 40),
        ("output", 64),
        ("concurrency", 2),
        ("temperature", 0.1),
        ("top_p", 0.9),
        ("scope", "full"),
        ("remote_model", "another-model"),
    ],
)
def test_mismatched_or_unknown_conditions_are_incomparable(key, value):
    result = compare_baseline(
        summary(), frozen_snapshot(), [baseline(conditions=conditions(**{key: value}))]
    )

    assert result["status"] == "incomparable"
    assert result["baseline_value"] is None
    assert result["measured_value"] is None
    assert result["difference"] is None


def test_unknown_extra_condition_is_not_silently_ignored():
    mismatched = conditions()
    del mismatched["remote_model"]
    mismatched["not_in_snapshot"] = "anything"

    result = compare_baseline(summary(), frozen_snapshot(), [baseline(conditions=mismatched)])

    assert result["status"] == "incomparable"
    assert result["difference"] is None


def test_different_dataset_is_never_matched_or_aggregated():
    other = baseline(dataset_key="MMMU-Pro", conditions=conditions(dataset_key="MMMU-Pro"))

    result = compare_baseline(summary(), frozen_snapshot(), [other])

    assert result["status"] == "incomparable"
    assert result["difference"] is None


def test_explicit_snapshot_dataset_overrides_gpqa_default():
    snapshot = {**frozen_snapshot(), "dataset_key": "MMMU-Pro"}

    result = compare_baseline(summary(), snapshot, [baseline()])

    assert result["status"] == "incomparable"
    assert result["baseline_value"] is None
    assert result["difference"] is None


def test_non_finite_measured_value_has_no_numeric_difference():
    result = compare_baseline(summary(accuracy=float("nan")), frozen_snapshot(), [baseline()])

    assert result["status"] == "matched"
    assert result["baseline_value"] == 40.0
    assert result["measured_value"] is None
    assert result["difference"] is None


def test_postgresql_ddl_contains_identity_and_provenance_constraints():
    ddl = str(CreateTable(BenchmarkBaseline.__table__).compile(dialect=postgresql.dialect()))

    assert "JSONB" in ddl
    assert "uq_benchmark_baseline_identity" in ddl
    assert "ck_benchmark_baseline_direction" in ddl
    assert "ck_benchmark_baseline_finite_value" in ddl
    assert "ck_benchmark_baseline_source_sha256" in ddl
    assert "ck_benchmark_baseline_content_sha256" in ddl
    assert "ck_benchmark_baseline_source_https" in ddl


def import_record(**changes):
    values = {
        "baseline_key": "fixture-baseline",
        "version": "fixture-v1",
        "dataset_key": DATASET_KEY,
        "subset_scope": "lite",
        "metric_name": "accuracy",
        "unit": "percent",
        "value": 40.0,
        "direction": "higher_is_better",
        "conditions": conditions(),
        "source_url": "https://example.invalid/fixture-baseline.json",
        "source_revision": "fixture-revision",
        "source_sha256": "c" * 64,
        "approved_by": "fixture-approver",
    }
    values.update(changes)
    return values


class FakeSession:
    def __init__(self):
        self.existing = None
        self.added = []

    async def scalar(self, statement):
        return self.existing

    def add(self, row):
        self.added.append(row)


async def test_import_is_canonically_idempotent_and_rejects_identity_conflict():
    session = FakeSession()
    original = import_record()

    imported = await import_baselines(session, {"baselines": [original]})
    assert len(imported) == 1
    assert len(imported[0].content_sha256) == 64
    session.existing = imported[0]

    reordered = import_record(
        conditions=dict(reversed(list(conditions().items()))),
    )
    reordered = dict(reversed(list(reordered.items())))
    duplicate = await import_baselines(session, {"baselines": [reordered]})

    assert duplicate[0] is imported[0]
    assert len(session.added) == 1
    with pytest.raises(BaselineConflictError, match="immutable"):
        await import_baselines(session, {"baselines": [import_record(value=41.0)]})
    assert imported[0].value == 40.0
    assert len(session.added) == 1


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
async def test_import_rejects_non_finite_values(value):
    with pytest.raises(ValidationError):
        await import_baselines(FakeSession(), {"baselines": [import_record(value=value)]})


@pytest.mark.parametrize("field", ["source_url", "source_revision", "source_sha256", "approved_by"])
async def test_import_requires_all_source_and_approval_fields(field):
    record = import_record()
    del record[field]

    with pytest.raises(ValidationError):
        await import_baselines(FakeSession(), {"baselines": [record]})


@pytest.mark.parametrize(
    "changes",
    [
        {"source_url": "http://example.invalid/baseline.json"},
        {"source_sha256": "C" * 64},
        {"source_sha256": "c" * 63},
    ],
)
async def test_import_enforces_https_and_lowercase_source_checksum(changes):
    with pytest.raises(ValidationError):
        await import_baselines(FakeSession(), {"baselines": [import_record(**changes)]})


async def test_import_rejects_unknown_fields_and_non_object_bundles():
    with pytest.raises(ValidationError):
        await import_baselines(FakeSession(), {"baselines": [], "extra": True})
    with pytest.raises(ValidationError):
        await import_baselines(
            FakeSession(), {"baselines": [import_record(content_sha256="d" * 64)]}
        )


@pytest.mark.skipif(not os.environ.get("AE_BASELINE_TEST"), reason="Live PostgreSQL required")
async def test_postgres_import_and_immutable_trigger_roll_back_without_fixture_residue():
    engine, sessions = create_database(get_settings())
    key = "live-" + uuid.uuid4().hex
    try:
        async with sessions() as session, session.begin():
            record = import_record(baseline_key=key)
            imported = await import_baselines(session, {"baselines": [record]})
            duplicate = await import_baselines(session, {"baselines": [record]})
            identifier = duplicate[0].id
            assert imported[0].id == identifier
            with pytest.raises(BaselineConflictError):
                await import_baselines(
                    session, {"baselines": [import_record(baseline_key=key, value=41)]}
                )
            with pytest.raises(DBAPIError):
                await session.execute(
                    text("UPDATE benchmark_baseline SET value = value + 1 WHERE id = :id"),
                    {"id": identifier},
                )
            await session.rollback()
        async with sessions() as session:
            assert await session.scalar(
                text("SELECT count(*) FROM benchmark_baseline WHERE baseline_key = :key"),
                {"key": key},
            ) == 0
    finally:
        await engine.dispose()
