import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import text

import app.models  # noqa: F401  (registers every table on Base.metadata)
from app.db.base import Base


@pytest.mark.anyio
async def test_core_schema_exists(db_session):
    result = await db_session.execute(
        text("SELECT 1 FROM information_schema.schemata WHERE schema_name = 'core'")
    )
    assert result.scalar() == 1


@pytest.mark.anyio
async def test_models_match_migrations(db_session):
    # Compares the table classes in Python with the tables the migrations built.
    # An empty list means they agree; anything else means a migration is missing
    # or a model is out of date.
    def diff(sync_conn):
        context = MigrationContext.configure(sync_conn, opts={"include_schemas": True})
        return compare_metadata(context, Base.metadata)

    conn = await db_session.connection()
    assert await conn.run_sync(diff) == []


def test_migrations_downgrade_and_upgrade_cleanly(alembic_cfg):
    # Proves every migration's downgrade() works, so a bad release can be rolled
    # back. Ends at head so the other tests still see the full schema.
    command.downgrade(alembic_cfg, "base")
    command.upgrade(alembic_cfg, "head")
