"""Alembic runs this file for every migration command."""

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

import app.models  # noqa: F401  (registers every table on Base.metadata)
from app.core.config import settings
from app.db.base import Base

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = Base.metadata


def get_url() -> str:
    # Tests point Alembic at the test database by setting sqlalchemy.url;
    # everywhere else we use the schema owner's MIGRATION_DATABASE_URL. Never fall
    # back to DATABASE_URL: the app's user isn't allowed to change tables.
    url = config.get_main_option("sqlalchemy.url") or settings.migration_database_url
    if not url:
        raise RuntimeError(
            "MIGRATION_DATABASE_URL is not set. Run migrations from the tools container: "
            "docker compose run --rm tools alembic upgrade head"
        )
    return url


def run_migrations_offline() -> None:
    """`alembic upgrade head --sql` prints the SQL instead of running it.

    Useful for reviewing exactly what will run on the Ministry server.
    """
    context.configure(url=get_url(), target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata, include_schemas=True)
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    engine = create_async_engine(get_url(), poolclass=NullPool)
    async with engine.connect() as connection:
        # Alembic's migration API is synchronous; run_sync bridges it onto our async connection.
        await connection.run_sync(do_run_migrations)
    await engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
