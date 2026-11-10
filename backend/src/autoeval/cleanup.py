"""Durable, independently retryable reclamation after immutable SSH evidence archival."""

import asyncio
import hashlib
import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from autoeval.audit import record_audit
from autoeval.case_history import CaseExecutionRecord
from autoeval.datasets import canonical_manifest, read_manifest
from autoeval.execution_transport import ssh_transport
from autoeval.models import Base, EvaluationRun, Record, RunSnapshot
from autoeval.runs import complete_cleanup


class ExecutionCleanup(Record, Base):
    __tablename__ = "execution_cleanup"
    run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("evaluation_run.id", ondelete="RESTRICT"), unique=True
    )
    state: Mapped[str] = mapped_column(String(16), default="pending")
    attempt_count: Mapped[int] = mapped_column(default=0)
    claim_token: Mapped[uuid.UUID | None]
    claimed_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    next_retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error_code: Mapped[str | None] = mapped_column(String(64))
    verified_proofs: Mapped[dict | None] = mapped_column(JSONB)
    __table_args__ = (
        CheckConstraint("state IN ('pending','running','failed','cleaned')"),
        CheckConstraint("attempt_count >= 0"),
        Index("ix_cleanup_due", "state", "next_retry_at"),
    )


async def schedule_cleanup(session, run_id):
    # Caller holds the run row lock, shared with the claimant.
    row = await session.scalar(select(ExecutionCleanup).where(ExecutionCleanup.run_id == run_id))
    if row is None:
        row = ExecutionCleanup(run_id=run_id)
        session.add(row)
    return row


def cleanup_view(row, *, required=True):
    return {
        "state": row.state if row else "not_scheduled" if required else "not_required",
        "attempt_count": row.attempt_count if row else 0,
        "last_error_code": row.last_error_code if row else None,
        "next_retry_at": row.next_retry_at.isoformat() if row and row.next_retry_at else None,
    }


async def reclaim(sessions, settings, run_id, *, force=False):
    from autoeval.evaluation_activity import _verified_report, model_payload
    from autoeval.evaluations import EvaluationReport

    now, token = datetime.now(UTC), uuid.uuid4()
    async with sessions() as session, session.begin():
        run = await session.scalar(
            select(EvaluationRun).where(EvaluationRun.id == run_id).with_for_update()
        )
        row = await session.scalar(
            select(ExecutionCleanup).where(ExecutionCleanup.run_id == run_id).with_for_update()
        )
        snapshot = await session.scalar(select(RunSnapshot).where(RunSnapshot.run_id == run_id))
        if row is None or snapshot is None or run is None:
            return "not_scheduled"
        frozen = snapshot.canonical_body
        if (
            run.state not in {"completed", "cancelled", "failed"}
            or frozen.get("resource_kind") != "customer_ssh"
            or frozen.get("execution_origin") != settings.evaluation_origin
        ):
            return "ineligible"
        if row.state == "cleaned":
            return "cleaned"
        if row.claimed_until and row.claimed_until > now:
            return "busy"
        if not force and row.next_retry_at and row.next_retry_at > now:
            return "deferred"
        row.state, row.claim_token = "running", token
        # A stale claimant may only repeat identical, proof-bound remote cleanup.
        row.claimed_until = now + timedelta(minutes=10)
        row.attempt_count += 1
        saved_proofs = row.verified_proofs or {}
    try:
        async with sessions() as session:
            report = await session.scalar(
                select(EvaluationReport).where(EvaluationReport.run_id == run_id)
            )
            if (
                report is None
                or hashlib.sha256(canonical_manifest(frozen)).hexdigest() != snapshot.sha256
            ):
                raise ValueError("Missing or inconsistent archive")
            body = await _verified_report(settings, report, run_id, snapshot)
            if report.snapshot_sha256 != snapshot.sha256:
                raise ValueError("Report snapshot reference differs")
            records = list(
                await session.scalars(
                    select(CaseExecutionRecord).where(CaseExecutionRecord.run_id == run_id)
                )
            )
        identities = {(str(r.id), r.sample_id, r.state) for r in records}
        reported = {(a["attempt_id"], a["sample_id"], a["state"]) for a in body["attempts"]}
        if identities != reported or len(reported) != len(body["attempts"]):
            raise ValueError("Attempt archive mismatch")
        bundle = await asyncio.to_thread(
            read_manifest, settings, SimpleNamespace(**frozen["dataset_content"])
        )
        members = {s["sample_id"]: s for s in bundle["samples"]}
        expected = {s["sample_id"]: s["sha256"] for s in frozen["samples"]}
        transport = await ssh_transport(sessions, settings, frozen)
        # Verify every archived case before deleting any remote evidence.
        verified = []
        for record in records:
            evidence = await asyncio.to_thread(read_manifest, settings, record)
            sample = members[record.sample_id]
            if (
                record.state == "started"
                or record.dataset_key != "GPQA"
                or sample["sha256"] != expected[record.sample_id]
                or hashlib.sha256(canonical_manifest(sample["native_sample"])).hexdigest()
                != expected[record.sample_id]
                or evidence.get("schema_version") != "case-evidence.v1"
                or evidence.get("attempt_id") != str(record.id)
                or evidence.get("state") != record.state
            ):
                raise ValueError("Case evidence mismatch")
            payload = model_payload(frozen, sample["native_sample"])
            saved = saved_proofs.get(str(record.id))
            observed = (
                await transport.lookup_request(str(record.id))
                if saved
                else await transport.collect_request(str(record.id), payload)
            )
            proof = {
                "request_sha256": transport.request_digest(payload),
                "result_sha256": observed.get("result_sha256"),
                "archive_sha256": record.sha256,
            }
            if saved:
                if (
                    saved != proof
                    or any(observed.get(k) != proof[k] for k in ("request_sha256", "result_sha256"))
                    or observed["state"] not in {"succeeded", "cleaned"}
                ):
                    raise ValueError("Previously verified cleanup receipt differs")
                if (
                    observed["state"] == "cleaned"
                    and observed.get("archive_sha256") != record.sha256
                ):
                    raise ValueError("Previously cleaned archive differs")
            elif observed["state"] == "cleaned":
                if any(observed.get(k) != v for k, v in proof.items()):
                    raise ValueError("Cleanup archive differs")
            elif observed["state"] == "succeeded":
                result = observed["result"]
                if result.get("tool_revision") != frozen["tool"]["revision"] or any(
                    result.get(k) != evidence.get(k)
                    for k in ("state", "prompt", "response", "finish_reason", "error_code", "usage")
                ):
                    raise ValueError("Remote result differs from archive")
            else:
                raise ValueError("Remote request is not confirmed terminal")
            verified.append((str(record.id), proof))
        async with sessions() as session, session.begin():
            row = await session.scalar(
                select(ExecutionCleanup).where(ExecutionCleanup.run_id == run_id).with_for_update()
            )
            if row.claim_token != token:
                return "superseded"
            row.verified_proofs = dict(verified)
        for key, proof in verified:
            if not (await transport.cleanup_request(key, proof)).get("cleaned"):
                raise ValueError("Remote cleanup unconfirmed")
    except Exception:  # noqa: BLE001 -- durable recovery boundary; never persist upstream secrets
        async with sessions() as session, session.begin():
            row = await session.scalar(
                select(ExecutionCleanup).where(ExecutionCleanup.run_id == run_id).with_for_update()
            )
            if row.claim_token == token:
                row.state, row.last_error_code = "failed", "ARCHIVE_OR_REMOTE_CLEANUP_UNCONFIRMED"
                row.claim_token = row.claimed_until = None
                row.next_retry_at = datetime.now(UTC) + timedelta(
                    seconds=min(3600, 60 * 2 ** min(row.attempt_count - 1, 6))
                )
                record_audit(
                    session,
                    action="execution.cleanup",
                    resource_id=str(run_id),
                    run_id=run_id,
                    outcome="failed",
                    request_id=f"cleanup:{token}",
                    details={"error_code": row.last_error_code, "ownership_retained": True},
                )
        return "failed"
    async with sessions() as session, session.begin():
        run = await session.scalar(
            select(EvaluationRun).where(EvaluationRun.id == run_id).with_for_update()
        )
        row = await session.scalar(
            select(ExecutionCleanup).where(ExecutionCleanup.run_id == run_id).with_for_update()
        )
        if row.claim_token != token:
            return "superseded"
        row.state, row.last_error_code = "cleaned", None
        row.claim_token = row.claimed_until = row.next_retry_at = None
        released = await complete_cleanup(session, run, observed_state="archived_native_requests")
        if not released:
            record_audit(
                session,
                action="execution.cleanup",
                resource_id=str(run_id),
                run_id=run_id,
                outcome="cleaned",
                request_id=f"cleanup:{token}",
                details={"observed_state": "archived_native_requests", "ownership_released": False},
            )
    return "cleaned"
