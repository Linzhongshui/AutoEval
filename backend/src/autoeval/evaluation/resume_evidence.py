"""Classify a frozen sample from reconciled execution and archived evidence."""

import asyncio
import math
import uuid
from collections.abc import Collection
from dataclasses import dataclass
from typing import Literal

from botocore.exceptions import BotoCoreError, ClientError
from sqlalchemy import select

from autoeval.catalog.datasets import read_manifest
from autoeval.reporting.models import CaseExecutionRecord


@dataclass(frozen=True)
class AttemptObservation:
    id: str
    state: Literal["started", "succeeded", "failed"]
    evidence_status: Literal["verified", "lost", "unavailable"]
    score: float | None


@dataclass(frozen=True)
class SampleDecision:
    category: Literal["reusable", "remaining", "evidence_lost", "unknown"]
    reason: str
    attempt_ids: tuple[str, ...] = ()


async def observe_archived_attempt(settings, record) -> AttemptObservation:
    identifier = str(record.id)
    if record.state == "started":
        return AttemptObservation(identifier, "started", "unavailable", None)
    try:
        body = await asyncio.to_thread(read_manifest, settings, record)
    except ClientError as exc:
        code = exc.response.get("Error", {}).get("Code")
        status = "lost" if code == "NoSuchKey" else "unavailable"
        return AttemptObservation(identifier, record.state, status, None)
    except ValueError:
        return AttemptObservation(identifier, record.state, "lost", None)
    except (BotoCoreError, OSError):
        return AttemptObservation(identifier, record.state, "unavailable", None)

    expected_status = "success" if record.state == "succeeded" else "failed"
    if (
        not isinstance(body, dict)
        or body.get("schema_version") != "unified-case.v1"
        or body.get("dataset_key") != record.dataset_key
        or body.get("sample_id") != record.sample_id
        or body.get("attempt_no") != record.attempt_no
        or body.get("status") != expected_status
    ):
        return AttemptObservation(identifier, record.state, "unavailable", None)
    score = body.get("score")
    return AttemptObservation(
        identifier, record.state, "verified", score if type(score) in (int, float) else None
    )


class ConfirmedEvidenceChanged(ValueError):
    """The confirmed evidence must be reviewed before a new round is accepted."""


async def verify_confirmed_reuse(session, settings, round_row):
    reusable = [row for row in round_row.selection["samples"] if row["category"] == "reusable"]
    if not reusable:
        return
    identifiers = [uuid.UUID(value) for row in reusable for value in row["attempt_ids"]]
    records = {
        str(record.id): record
        for record in await session.scalars(
            select(CaseExecutionRecord).where(
                CaseExecutionRecord.run_id == round_row.run_id,
                CaseExecutionRecord.id.in_(identifiers),
            )
        )
    }
    for row in reusable:
        group = [records.get(value) for value in row["attempt_ids"]]
        if any(
            record is None
            or record.dataset_key != row["dataset_key"]
            or record.sample_id != row["sample_id"]
            for record in group
        ):
            raise ConfirmedEvidenceChanged("Confirmed attempt identity changed")
        if "evidence_sha256" in row and [r.sha256 for r in group] != row["evidence_sha256"]:
            raise ConfirmedEvidenceChanged("Confirmed evidence identity changed")
        for record in group:
            observation = await observe_archived_attempt(settings, record)
            if observation.evidence_status == "lost":
                raise ConfirmedEvidenceChanged("Confirmed reuse evidence was lost")
            if observation.evidence_status != "verified":
                raise ValueError("Confirmed reuse evidence is not available")


def terminal_attempt_group(records, expected_attempts):
    """A full native attempt group is terminal evidence even in a cancelled job."""
    if len(records) != expected_attempts or any(record.state == "started" for record in records):
        return False
    native_numbers = {
        (record.tool_metadata or {}).get("native_attempt_no", record.attempt_no)
        for record in records
    }
    return native_numbers == set(range(1, expected_attempts + 1))


def classify_sample(
    attempts: Collection[AttemptObservation],
    *,
    expected_attempts: int,
    dispatch_reconciled: bool,
) -> SampleDecision:
    """Inspect one native attempt group without combining multiple executions."""
    if not dispatch_reconciled or any(attempt.state == "started" for attempt in attempts):
        return SampleDecision("unknown", "dispatch_unresolved")
    if any(attempt.evidence_status == "unavailable" for attempt in attempts):
        return SampleDecision("unknown", "evidence_unavailable")
    ids = tuple(attempt.id for attempt in attempts)
    if expected_attempts < 1 or len(set(ids)) != len(ids) or len(ids) > expected_attempts:
        return SampleDecision("unknown", "attempt_identity_conflict")
    if any(
        attempt.state == "succeeded" and attempt.evidence_status == "lost" for attempt in attempts
    ):
        return SampleDecision("evidence_lost", "completed_evidence_lost", ids)
    if len(attempts) != expected_attempts or any(attempt.state == "failed" for attempt in attempts):
        return SampleDecision("remaining", "missing_or_failed_attempt", ids)
    if any(attempt.score is None or not math.isfinite(attempt.score) for attempt in attempts):
        return SampleDecision("remaining", "scoring_incomplete", ids)
    return SampleDecision("reusable", "verified_attempts", ids)
