"""Initial run outbox dispatcher. Report/analysis intents are not enabled yet."""

import asyncio
import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from temporalio.client import Client
from temporalio.common import WorkflowIDReusePolicy
from temporalio.exceptions import WorkflowAlreadyStartedError

from autoeval.config import get_settings
from autoeval.db import create_database
from autoeval.models import Outbox
from autoeval.workflows import RunWorkflow

log = logging.getLogger(__name__)


async def deliver_once(sessions, client) -> bool:
    # Keep a bounded single-row transaction during dispatch: rollback releases
    # the row after a crash, while a stable Workflow ID handles re-delivery.
    async with sessions() as session, session.begin():
        row = await session.scalar(
            select(Outbox)
            .where(Outbox.state == "pending", Outbox.next_retry_at <= datetime.now(UTC))
            .order_by(Outbox.created_at, Outbox.id)
            .with_for_update(skip_locked=True)
            .limit(1)
        )
        if row is None:
            return False
        if row.kind != "START_RUN":
            row.next_retry_at = datetime.now(UTC) + timedelta(minutes=1)
            log.error("Unsupported outbox intent id=%s kind=%s", row.id, row.kind)
            return True
        try:
            await asyncio.wait_for(
                client.start_workflow(
                    RunWorkflow.run,
                    str(row.run_id),
                    id=f"demo/run/{row.run_id}",
                    task_queue="demo.workflow.v1",
                    id_reuse_policy=WorkflowIDReusePolicy.REJECT_DUPLICATE,
                ),
                timeout=5,
            )
        except WorkflowAlreadyStartedError:
            pass
        except Exception:  # noqa: BLE001 -- delivery uncertainty is retried with the same Workflow ID
            row.attempt_count += 1
            row.next_retry_at = datetime.now(UTC) + timedelta(seconds=30)
            log.warning("Outbox delivery deferred id=%s", row.id)
            return True
        row.state = "delivered"
        row.attempt_count += 1
        return True


async def serve():
    settings = get_settings()
    engine, sessions = create_database(settings)
    try:
        client = await Client.connect(
            settings.temporal_address, namespace=settings.temporal_namespace
        )
        while True:
            if not await deliver_once(sessions, client):
                await asyncio.sleep(settings.poll_seconds)
    finally:
        await engine.dispose()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(serve())
