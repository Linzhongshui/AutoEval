import asyncio
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from autoeval.catalog.datasets import canonical_manifest, write_manifest
from autoeval.catalog.standard_inputs import digest
from autoeval.evaluation.inputs import selection_identity

PREFLIGHT_TTL = timedelta(minutes=5)


async def artifact(session, settings, kind, payload):
    from autoeval.planning.models import PlanningArtifact

    raw = canonical_manifest(payload)
    sha = digest(payload)
    key = f"planning/{kind}/{sha}.json"
    await asyncio.to_thread(write_manifest, settings, key, raw)
    row = PlanningArtifact(kind=kind, sha256=sha, object_key=key, payload=payload)
    session.add(row)
    await session.flush()
    return row


async def current_preflight(session, inputs, *, probe_container=None):
    from autoeval.planning.models import PlanningArtifact

    rows = (
        await session.scalars(
            select(PlanningArtifact)
            .where(PlanningArtifact.kind == "resource")
            .order_by(PlanningArtifact.created_at.desc())
            .limit(100)
        )
    ).all()
    row = next(
        (
            r
            for r in rows
            if all(r.payload.get(k) == inputs[k] for k in ("resource_id", "resource_kind"))
            and (
                (
                    r.payload.get("resource_ids", []) == inputs.get("resource_ids", [])
                    and r.payload.get("target_id") == inputs.get("target_id")
                    and selection_identity(r.payload) == selection_identity(inputs)
                )
                if probe_container is None
                else (
                    all(probe_container)
                    and r.payload.get("planning_container") == probe_container
                    and r.payload.get("planner_ready") is True
                    and not r.payload.get("execution_templates")
                    and r.payload.get("resource_ids", []) in ([], [inputs["resource_id"]])
                )
            )
            and r.created_at > datetime.now(UTC) - PREFLIGHT_TTL
        ),
        None,
    )
    if (
        row
        and (expires := row.payload.get("preflight_valid_until"))
        and datetime.fromisoformat(expires) <= datetime.now(UTC)
    ):
        return None
    return row
