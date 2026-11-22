"""Persist a confirmed follow-up together with its dispatch intent."""

import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from autoeval.catalog.standard_inputs import digest
from autoeval.evaluation.models import ExecutionRound, ExecutionShard, RoundRequest
from autoeval.evaluation.task_monitor import MonitorBinding
from autoeval.infrastructure.models import EvaluationRun, Outbox, RunEvent


@dataclass(frozen=True)
class ConfirmedScope:
    snapshot_sha256: str
    scope_sha256: str
    selection: dict
    shards: list[dict]


async def submit_follow_up(
    session: AsyncSession,
    run_id: uuid.UUID,
    *,
    operation: str,
    source_number: int,
    scope_sha256: str,
    key: str,
    target: dict,
    resolve_scope: Callable[[AsyncSession, EvaluationRun], Awaitable[ConfirmedScope]],
) -> ExecutionRound:
    """Called within the request transaction; resolve eligibility under the task lock."""
    run = await session.get(EvaluationRun, run_id, with_for_update=True)
    if run is None or run.trigger_scope != "local-operator:orchestration":
        raise HTTPException(404, "Evaluation task not found")
    request_hash = digest(
        {
            "operation": operation,
            "source_round": source_number,
            "scope_sha256": scope_sha256,
            "target": target,
        }
    )
    prior = await session.scalar(
        select(RoundRequest).where(
            RoundRequest.run_id == run_id, RoundRequest.idempotency_key == key
        )
    )
    if prior is not None:
        if prior.request_sha256 != request_hash:
            raise HTTPException(409, "Idempotency content conflict")
        return await session.get_one(ExecutionRound, prior.round_id)

    successor = await session.scalar(
        select(ExecutionRound).where(
            ExecutionRound.run_id == run_id, ExecutionRound.source_number == source_number
        )
    )
    if successor is not None:
        if (
            successor.operation != operation
            or successor.scope_sha256 != scope_sha256
            or successor.selection["target"] != target
        ):
            raise HTTPException(409, "Source round already has a different successor")
    else:
        current = await session.scalar(
            select(ExecutionRound.number)
            .where(ExecutionRound.run_id == run_id)
            .order_by(ExecutionRound.number.desc())
            .limit(1)
        )
        if source_number != (current if current is not None else 1):
            raise HTTPException(409, "Source round changed")
        if run.state not in {"completed", "cancelled", "failed"}:
            raise HTTPException(409, "Source round is active")
        scope = await resolve_scope(session, run)
        if scope.scope_sha256 != scope_sha256:
            raise HTTPException(409, "Confirmed scope changed")
        successor = ExecutionRound(
            id=uuid.uuid4(),
            run_id=run_id,
            number=source_number + 1,
            source_number=source_number,
            operation=operation,
            actor=run.created_by,
            snapshot_sha256=scope.snapshot_sha256,
            scope_sha256=scope_sha256,
            selection={**scope.selection, "target": target, "source_state": run.state},
        )
        session.add(successor)
        await session.flush()
        last_binding = (
            await session.scalar(
                select(func.max(MonitorBinding.attempt)).where(MonitorBinding.run_id == run_id)
            )
            or 0
        )
        for position, payload in enumerate(scope.shards):
            shard_id = uuid.uuid4()
            session.add(
                ExecutionShard(
                    id=shard_id,
                    round_id=successor.id,
                    task_id=payload["task_id"],
                    position=position,
                    payload=payload,
                )
            )
            session.add(
                MonitorBinding(
                    run_id=run_id,
                    attempt=last_binding + position + 1,
                    identity={
                        "child_id": str(shard_id),
                        "task_name": str(shard_id),
                        "dataset": payload["dataset"],
                        "round": successor.number,
                    },
                )
            )
        run.projection_version += 1
        session.add(
            RunEvent(
                run_id=run_id,
                seq=run.projection_version,
                type="follow_up_queued",
                body={
                    "operation": operation,
                    "source_round": source_number,
                    "round": successor.number,
                    "source_state": run.state,
                    "source_cancel_requested_at": (
                        run.cancel_requested_at.isoformat() if run.cancel_requested_at else None
                    ),
                },
            )
        )
        run.state = "queued"
        run.cancel_requested_at = None
        session.add(
            Outbox(
                run_id=run_id,
                kind="START_RUN",
                dedup_key=f"evaluation-round:{successor.id}",
                payload={
                    "workflow_kind": "evaluation_follow_up",
                    "round_id": str(successor.id),
                    **(
                        {"workflow_queue": "autoeval.dataset-containers.v1"}
                        if any(shard.get("execution_template") for shard in scope.shards)
                        else {}
                    ),
                },
            )
        )

    session.add(
        RoundRequest(
            run_id=run_id,
            round_id=successor.id,
            idempotency_key=key,
            request_sha256=request_hash,
        )
    )
    return successor
