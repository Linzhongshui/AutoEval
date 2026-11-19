"""Durable Harbor trace imports; scoring is independent of observability."""

import asyncio
import base64
import hashlib
import tempfile
import uuid
from pathlib import Path
from urllib.parse import quote

import httpx
from fastapi import APIRouter, HTTPException, Request
from sqlalchemy import ForeignKey, String, UniqueConstraint, select
from sqlalchemy.orm import Mapped, mapped_column
from temporalio import activity

from autoeval.datasets import canonical_manifest, read_manifest, write_manifest
from autoeval.models import Base, EvaluationRun, Outbox, Record
from autoeval.reporting.harbor_trace import FILES, build_plan  # noqa: F401

REVISION = "a62c1be62888e2cb5c89f92aa2dc00731f4f5ed1"


class TraceImport(Record, Base):
    __tablename__ = "langfuse_trace_import"
    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("evaluation_run.id"))
    attempt_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("case_execution_record.id"))
    langfuse_project: Mapped[str] = mapped_column(String(128))
    object_key: Mapped[str] = mapped_column(String(256))
    sha256: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(32))
    trace_id: Mapped[str | None] = mapped_column(String(32))
    error_code: Mapped[str | None] = mapped_column(String(64))
    retry_no: Mapped[int] = mapped_column(default=0)
    content_mode: Mapped[str] = mapped_column(
        String(16), default="structural", server_default="structural"
    )
    __table_args__ = (UniqueConstraint("attempt_id", "langfuse_project"),)


def intent(session, row):
    session.add(
        Outbox(
            run_id=row.run_id,
            kind="START_RUN",
            dedup_key=f"trace/{row.id}/{row.retry_no}",
            payload={
                "workflow_kind": "langfuse_import",
                "import_id": str(row.id),
                "retry_no": row.retry_no,
                "workflow_queue": "demo.langfuse.v1",
            },
        )
    )


async def archive_trace(session, settings, run_id, attempt_id, artifact):
    raw = canonical_manifest(artifact or {"files": {}})
    digest = hashlib.sha256(raw).hexdigest()
    key = f"harbor-traces/{run_id}/{attempt_id}/{digest}.json"
    await asyncio.to_thread(write_manifest, settings, key, raw)
    files = (artifact or {}).get("files", {})
    status = "pending" if "agent/trajectory.json" in files else "missing"
    if status == "pending" and not import_configured(settings):
        status = "disabled"
    row = TraceImport(
        id=uuid.uuid4(),
        run_id=run_id,
        attempt_id=attempt_id,
        langfuse_project=settings.langfuse_project_id or "unconfigured",
        object_key=key,
        sha256=digest,
        status=status,
        retry_no=0,
        content_mode=settings.langfuse_content_mode,
    )
    session.add(row)
    if status == "pending":
        intent(session, row)


def import_configured(settings):
    return all(
        (
            settings.langfuse_project_id,
            settings.langfuse_host,
            settings.langfuse_browser_url,
            settings.langfuse_public_key.get_secret_value(),
            settings.langfuse_secret_key.get_secret_value(),
        )
    )


def trace_view(row, settings):
    if row is None:
        return {
            "trace_status": "unsupported",
            "trace_id": None,
            "trace_url": None,
            "trace_content_mode": None,
        }
    url = None
    if row.status == "succeeded" and settings.langfuse_browser_url:
        url = (
            settings.langfuse_browser_url.rstrip("/")
            + "/project/"
            + quote(row.langfuse_project, safe="")
            + "/traces/"
            + quote(row.trace_id, safe="")
        )
    return {
        "trace_status": row.status,
        "trace_id": row.trace_id if url else None,
        "trace_url": url,
        "trace_error": row.error_code,
        "trace_content_mode": getattr(row, "content_mode", "structural"),
    }


async def import_one(row, settings, artifact):
    from harborstack.convert.export import Exporter
    from harborstack.convert.scores import backfill

    if not settings.langfuse_host or not settings.langfuse_browser_url:
        raise ValueError("Langfuse not configured")
    with tempfile.TemporaryDirectory() as tmp:
        rec, plan = build_plan(
            artifact, Path(tmp), str(row.attempt_id), getattr(row, "content_mode", "structural")
        )
        trace_id = format(plan[0].trace_id, "032x")
        host = settings.langfuse_host.rstrip("/")
        public = settings.langfuse_public_key.get_secret_value()
        secret = settings.langfuse_secret_key.get_secret_value()
        auth = base64.b64encode(f"{public}:{secret}".encode()).decode()
        async with httpx.AsyncClient(
            timeout=15, headers={"Authorization": "Basic " + auth}
        ) as client:
            expected_ids = {format(spec.span_id, "016x") for spec in plan}

            async def observation_ids():
                found, cursors = set(), set()
                cursor = None
                while True:
                    params = {"traceId": trace_id, "limit": 1000}
                    if cursor:
                        params["cursor"] = cursor
                    response = await client.get(host + "/api/public/v2/observations", params=params)
                    response.raise_for_status()
                    payload = response.json()
                    found.update(item["id"] for item in payload.get("data", []))
                    cursor = (payload.get("meta") or {}).get("nextCursor")
                    if not cursor:
                        return found
                    if cursor in cursors:
                        raise RuntimeError("Observation pagination did not advance")
                    cursors.add(cursor)

            # A failed lookup must never be interpreted as absence. A partial trace
            # must not be marked successful or blindly resent (v4 may duplicate spans).
            existing = await observation_ids()
            if existing and not expected_ids <= existing:
                raise RuntimeError("Partial trace ingestion; automatic resend refused")
            if not existing:

                def send():
                    exporter = Exporter(host, public, secret)
                    try:
                        exporter.send(plan)
                        exporter.flush()
                    finally:
                        exporter.shutdown()

                await asyncio.to_thread(send)
            for _ in range(10):
                if expected_ids <= await observation_ids():
                    break
                await asyncio.sleep(2)
            else:
                raise RuntimeError("Trace ingestion not confirmed")
            scores = await asyncio.to_thread(
                backfill,
                host,
                public,
                secret,
                {"trace_id": trace_id, "observation_id": format(plan[0].span_id, "016x")},
                rec,
                timestamp=plan[0].start_ts,
            )
            if any(status is None or status >= 300 for _, status, _ in scores):
                raise RuntimeError("Score ingestion not confirmed")
        return trace_id


@activity.defn
async def import_harbor_trace(identifier: str):
    from autoeval.config import get_settings
    from autoeval.db import create_database

    settings = get_settings()
    engine, sessions = create_database(settings)
    try:
        async with sessions() as session, session.begin():
            row = await session.scalar(
                select(TraceImport).where(TraceImport.id == uuid.UUID(identifier)).with_for_update()
            )
            if row is None or row.status == "succeeded":
                return
            try:
                artifact = await asyncio.to_thread(read_manifest, settings, row)
                row.trace_id = await import_one(row, settings, artifact)
                row.status, row.error_code = "succeeded", None
            except Exception:  # noqa: BLE001 -- never persist third-party secrets/errors
                row.status, row.error_code = "failed", "TRACE_IMPORT_FAILED"
    finally:
        await engine.dispose()


router = APIRouter(prefix="/api/autoeval/v1", tags=["Langfuse"])


@router.get("/runs/{run_id}/traces")
async def traces(run_id: uuid.UUID, request: Request):
    async with request.app.state.sessions() as session:
        if await session.get(EvaluationRun, run_id) is None:
            raise HTTPException(404, "Run not found")
        rows = (
            await session.scalars(select(TraceImport).where(TraceImport.run_id == run_id))
        ).all()
        return {
            "data": [
                {"attempt_id": str(r.attempt_id), **trace_view(r, request.app.state.settings)}
                for r in rows
            ],
            "request_id": request.state.request_id,
        }


@router.post("/runs/{run_id}/traces/retry")
async def retry(run_id: uuid.UUID, request: Request):
    async with request.app.state.sessions() as session, session.begin():
        if await session.get(EvaluationRun, run_id) is None:
            raise HTTPException(404, "Run not found")
        rows = (
            await session.scalars(
                select(TraceImport)
                .where(TraceImport.run_id == run_id, TraceImport.status == "failed")
                .with_for_update()
            )
        ).all()
        for row in rows:
            row.retry_no += 1
            row.status, row.error_code = "pending", None
            intent(session, row)
        return {"data": {"queued": len(rows)}, "request_id": request.state.request_id}
