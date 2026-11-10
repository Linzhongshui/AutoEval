import asyncio

from alembic import context

import autoeval.analysis
import autoeval.benchmarks
import autoeval.case_history
import autoeval.configuration
import autoeval.datasets
import autoeval.evaluations
import autoeval.profiles
import autoeval.registry
import autoeval.resources
import autoeval.runs
import autoeval.targets  # noqa: F401 -- register endpoint/probe tables
from autoeval.config import get_settings
from autoeval.db import create_database
from autoeval.models import Base

config = context.config
target_metadata = Base.metadata


def migrate(connection):
    context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


async def online():
    engine, _ = create_database(get_settings())
    async with engine.connect() as conn:
        await conn.run_sync(migrate)
    await engine.dispose()


if context.is_offline_mode():
    context.configure(
        url=get_settings().database_url.get_secret_value(),
        target_metadata=target_metadata,
        literal_binds=True,
    )
    with context.begin_transaction():
        context.run_migrations()
else:
    asyncio.run(online())
