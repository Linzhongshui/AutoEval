"""Retry removal only after the child has committed its terminal result."""

import logging
from datetime import UTC, datetime

from sqlalchemy import select

from autoeval.evaluation.models import DatasetExecutionEnvironment
from autoeval.evaluation.resource_allocation import release
from autoeval.planning.planning_transport import isolated_transport

log = logging.getLogger(__name__)


async def reclaim_pending(sessions, settings):
    model = DatasetExecutionEnvironment
    async with sessions() as session:
        owners = list(
            await session.scalars(
                select(model.dataset_execution_id)
                .where(model.state == "cleanup_pending")
                .order_by(
                    model.cleanup_attempted_at.asc().nulls_first(), model.dataset_execution_id
                )
                .limit(100)
            )
        )
    for owner in owners:
        await reclaim_child(sessions, settings, owner)


async def reclaim_child(sessions, settings, owner):
    try:
        async with sessions() as session, session.begin():
            row = await session.get(DatasetExecutionEnvironment, owner, with_for_update=True)
            if row is None or row.state != "cleanup_pending":
                return
            row.cleanup_attempted_at = datetime.now(UTC)
            try:
                adapter = await isolated_transport(
                    session, settings, row.resource_id, owner, row.template
                )
                removed = await adapter.remove()
            except (OSError, RuntimeError, ValueError):
                log.warning("Isolated cleanup deferred for child %s", owner)
                return
            if removed:
                await release(session, owner)
                row.state = "cleaned"
    except Exception:  # noqa: BLE001 -- isolate failures and retain capacity for retry
        log.warning("Isolated cleanup deferred for child %s", owner)
