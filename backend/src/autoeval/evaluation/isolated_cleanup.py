"""Retry removal only after the child has committed its terminal result."""

import logging

from sqlalchemy import select

from autoeval.evaluation.models import DatasetExecutionEnvironment
from autoeval.evaluation.resource_allocation import release
from autoeval.planning.planning_transport import isolated_transport

log = logging.getLogger(__name__)


async def reclaim_pending(sessions, settings):
    model = DatasetExecutionEnvironment
    async with sessions() as session:
        owners = list(await session.scalars(
            select(model.dataset_execution_id).where(model.state == "cleanup_pending").limit(100)
        ))
    for owner in owners:
        try:
            async with sessions() as session, session.begin():
                row = await session.get(model, owner, with_for_update=True)
                if row.state != "cleanup_pending":
                    continue
                adapter = await isolated_transport(session, settings, row.resource_id, owner, row.template)
                if await adapter.remove():
                    await release(session, owner)
                    row.state = "cleaned"
        except Exception:  # noqa: BLE001 -- isolate failures and retain capacity for retry
            log.warning("Isolated cleanup deferred for child %s", owner)
