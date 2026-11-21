"""Reuse evidence from a completed isolated check, never its execution container."""

from datetime import UTC, datetime

from sqlalchemy import select, text

from autoeval.catalog.standard_inputs import digest
from autoeval.planning.artifacts import PREFLIGHT_TTL, artifact
from autoeval.planning.models import PlanningArtifact
from autoeval.planning.planning_transport import execution_template
from autoeval.resources.models import SSHResourceBinding
from autoeval.resources.ssh_resources import resource_data


def evidence_expires_at(evidence):
    return datetime.fromisoformat(evidence["checked_at"]) + PREFLIGHT_TTL


async def cached_isolated_check(sessions, settings, job_id, item, check, report, run):
    resource_id = item["assigned_resource_id"]
    async with sessions() as session, session.begin():
        binding = await session.get(SSHResourceBinding, resource_id)
        if binding is None:
            raise ValueError("SSH binding missing")
        key = digest(
            {
                "format": 1,
                "ssh": {**resource_data(binding), "credential_ref": binding.credential_ref},
                "task": item,
            }
        )
        # Concurrent preflight jobs for this exact binding share one real check.
        await session.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
            {"key": "dataset-preflight:" + key},
        )
        if execution_template(settings, resource_id, item) == item["execution_template"]:
            now = datetime.now(UTC)
            prior = await session.scalar(
                select(PlanningArtifact.payload)
                .where(
                    PlanningArtifact.kind == "dataset_preflight",
                    PlanningArtifact.created_at > now - PREFLIGHT_TTL,
                    PlanningArtifact.payload["cache_key"].astext == key,
                )
                .order_by(PlanningArtifact.created_at.desc())
                .limit(1)
            )
            if prior and evidence_expires_at(prior["result"]["preflight_evidence"]) > now:
                return prior["result"], True

        result = await run(sessions, settings, job_id, item, check, report)
        if result["execution_ready"] and result.get("preflight_evidence"):
            await artifact(
                session, settings, "dataset_preflight", {"cache_key": key, "result": result}
            )
        return result, False
