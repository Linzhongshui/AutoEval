from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from autoeval.config import Settings


def create_database(settings: Settings):
    engine = create_async_engine(
        settings.database_url.get_secret_value(),
        pool_pre_ping=True,
        connect_args={"timeout": settings.dependency_timeout_seconds},
    )
    return engine, async_sessionmaker(engine, expire_on_commit=False)
