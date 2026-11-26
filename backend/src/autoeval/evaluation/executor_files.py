"""Developer-only, read-only access to the files of a specific execution attempt."""

import asyncio
import uuid
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel
from sqlalchemy import select

from autoeval.evaluation.archived_executor_files import archived_files
from autoeval.evaluation.models import DatasetExecution, ExecutionRound, ExecutionShard
from autoeval.evaluation.resource_allocation import resource_for_task
from autoeval.infrastructure.models import EvaluationRun, RunSnapshot
from autoeval.infrastructure.responses import Envelope, envelope
from autoeval.planning.debug_storage import STORAGE_ERRORS, browse_store
from autoeval.planning.planning_transport import transport
from autoeval.resources.models import ResourceBinding


class ExecutorAttempt(BaseModel):
    id: uuid.UUID
    dataset: str
    round: int


class ExecutorEntry(BaseModel):
    metadata_only: bool = False
    name: str
    directory: bool
    size: int
    mtime: float


class ExecutorDirectory(BaseModel):
    state: Literal["directory"]
    archived: bool | None = None
    entries: list[ExecutorEntry]
    more: bool


class ExecutorPreview(BaseModel):
    state: Literal["text"]
    content: str
    start: int
    end: int
    size: int


class ExecutorFileStatus(BaseModel):
    state: Literal[
        "binary",
        "pending",
        "removed",
        "missing_file",
        "unverified",
        "unavailable",
        "wrong_storage",
        "protected",
    ]
    size: int | None = None


def require_development(request: Request, response: Response):
    response.headers["Cache-Control"] = "no-store"
    if request.app.state.settings.environment not in {"development", "test"}:
        raise HTTPException(403, "Executor diagnostics are development-only")


router = APIRouter(
    prefix="/api/autoeval/v1/evaluation-tasks",
    tags=["executor files"],
    dependencies=[Depends(require_development)],
)


@router.get("/{run_id}/executor-files", response_model=Envelope[list[ExecutorAttempt]])
async def attempts(run_id: uuid.UUID, request: Request):
    async with request.app.state.sessions() as session:
        if await session.get(EvaluationRun, run_id) is None:
            raise HTTPException(404, "Task not found")
        snapshot = await session.scalar(select(RunSnapshot).where(RunSnapshot.run_id == run_id))
        if snapshot and snapshot.schema_version == "fixture.v1":
            source = snapshot.canonical_body.get("fixture_source_job")
            data = [{"id": source, "dataset": "validation-dataset", "round": 1}] if source else []
            return envelope(data, request)
        initial = await session.scalars(
            select(DatasetExecution)
            .where(DatasetExecution.run_id == run_id)
            .order_by(DatasetExecution.task_id)
        )
        data = [
            {"id": str(row.id), "dataset": row.payload["dataset"], "round": 1} for row in initial
        ]
        later = await session.execute(
            select(ExecutionRound.number, ExecutionShard)
            .join(ExecutionShard, ExecutionShard.round_id == ExecutionRound.id)
            .where(ExecutionRound.run_id == run_id)
            .order_by(ExecutionRound.number, ExecutionShard.position)
        )
        data.extend(
            {"id": str(row.id), "dataset": row.payload["dataset"], "round": number}
            for number, row in later
        )
    return envelope(data, request)


@router.get(
    "/{run_id}/executor-files/{job_id}",
    response_model=Envelope[ExecutorDirectory | ExecutorPreview | ExecutorFileStatus],
    response_model_exclude_none=True,
)
async def files(
    run_id: uuid.UUID,
    job_id: uuid.UUID,
    request: Request,
    view: Literal["directory", "outputs", "archive", "archive-directory"] = "directory",
    path: str = Query("", max_length=2048),
    offset: int = Query(0, ge=0),
):
    settings = request.app.state.settings
    async with request.app.state.sessions() as session:
        job = await session.scalar(
            select(DatasetExecution).where(
                DatasetExecution.run_id == run_id, DatasetExecution.id == job_id
            )
        )
        if job is None:
            job = await session.scalar(
                select(ExecutionShard)
                .join(ExecutionRound)
                .where(ExecutionRound.run_id == run_id, ExecutionShard.id == job_id)
            )
        snapshot = await session.scalar(select(RunSnapshot).where(RunSnapshot.run_id == run_id))
        frozen = snapshot.canonical_body if snapshot else {}
        if job is None:
            if (
                not snapshot
                or snapshot.schema_version != "fixture.v1"
                or frozen.get("fixture_source_job") != str(job_id)
            ):
                raise HTTPException(404, "Job not found in task")
            resource = frozen
            if view in {"archive", "archive-directory"}:
                return envelope({"state": "missing_file"}, request)
            binding = frozen["resource"]["debug_storage"]
        else:
            if view in {"archive", "archive-directory"}:
                return envelope(
                    await archived_files(
                        session,
                        settings,
                        run_id,
                        job,
                        path,
                        offset,
                        directory=view == "archive-directory",
                    )
                    or {"state": "missing_file"},
                    request,
                )
            binding = resource_for_task(frozen.get("resource", {}), job.task_id).get(
                "debug_storage"
            )
            if not binding:
                archived = await archived_files(
                    session, settings, run_id, job, path, offset, directory=view == "directory"
                )
                if archived:
                    return envelope(archived, request)
                if job.state in {"pending", "queued", "preparing", "submitting", "running"}:
                    return envelope({"state": "pending"}, request)
                return envelope({"state": "unverified"}, request)
            inputs = frozen["inputs"]
            task = next(t for t in inputs["tasks"] if t["task_id"] == job.task_id)
            resource = {
                "resource_id": task.get("assigned_resource_id") or inputs["resource_id"],
                "resource_kind": task.get("assigned_resource_kind") or inputs["resource_kind"],
            }
        try:
            adapter = await transport(session, settings, resource)
            query = {"job": str(job_id), "path": path, "offset": offset, "view": view}
            result = await asyncio.to_thread(browse_store, adapter, binding, query)
            if (
                result["state"] in {"unavailable", "wrong_storage"}
                and resource["resource_kind"] == "docker_local"
            ):
                registered = list(
                    await session.scalars(
                        select(ResourceBinding.container_id).order_by(
                            ResourceBinding.created_at.desc()
                        )
                    )
                )
                alternatives = [value for value in registered if value != adapter.container_id]
                if alternatives:
                    result = await asyncio.to_thread(
                        browse_store, adapter, binding, query, alternatives
                    )
        except STORAGE_ERRORS:
            result = {"state": "unavailable"}
        if job is not None and (
            result["state"] in {"removed", "pending", "unavailable", "wrong_storage"}
            or (
                view == "outputs"
                and result["state"] == "directory"
                and not result["entries"]
                and not offset
            )
        ):
            archived = await archived_files(
                session, settings, run_id, job, path, offset, directory=view == "directory"
            )
            if archived:
                result = archived
    if result["state"] == "forbidden":
        raise HTTPException(403, "Protected path")
    return envelope(result, request)
