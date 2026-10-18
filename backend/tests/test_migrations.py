import pytest
from alembic import command
from sqlalchemy import text


@pytest.mark.anyio
async def test_core_schema_exists(db_session):
    result = await db_session.execute(
        text("SELECT 1 FROM information_schema.schemata WHERE schema_name = 'core'")
    )
    assert result.scalar() == 1


def test_migrations_downgrade_and_upgrade_cleanly(alembic_cfg):
    # Proves every migration's downgrade() works, so a bad release can be rolled
    # back. Ends at head so the other tests still see the full schema.
    command.downgrade(alembic_cfg, "base")
    command.upgrade(alembic_cfg, "head")
