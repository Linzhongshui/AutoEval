"""Session advisory leases advertise live probe consumers without starting any jobs."""

from sqlalchemy import text


def consumer_key(job_id=None):
    return "autoeval:probe-consumer" + (":" + str(job_id) if job_id else "")


async def consumer_ready(session, job_id=None, created_at=None):
    for key in [*([consumer_key(job_id)] if job_id else []), consumer_key()]:
        free = await session.scalar(
            text("SELECT pg_try_advisory_xact_lock(hashtext(:key))"), {"key": key}
        )
        if not free:
            if key == consumer_key() and created_at is not None:
                cutoff = await session.scalar(
                    text(
                        "SELECT max(objid::bigint) FROM pg_locks WHERE locktype='advisory' AND classid=1095062608 AND objsubid=2 AND granted"
                    )
                )
                if cutoff is not None and created_at.timestamp() < cutoff:
                    continue
            return True
    return False
