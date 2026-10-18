"""Shared test setup.

Tests run against a separate database (<your db name>_test) so they never touch
dev data. Each test runs inside a transaction that is rolled back at the end, so
every test starts from the same clean state.

Async tests use the anyio pytest plugin, which ships with FastAPI's dependencies:
mark a test module with `pytestmark = pytest.mark.anyio`.
"""

import asyncio
from pathlib import Path

import asyncpg
import pytest
from alembic import command
from alembic.config import Config
from httpx import ASGITransport, AsyncClient
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import settings
from app.db.session import get_session
from app.main import app

BACKEND_DIR = Path(__file__).resolve().parent.parent

_dev_url = make_url(settings.database_url)
TEST_DATABASE_URL = _dev_url.set(database=f"{_dev_url.database}_test")

# NullPool: open a fresh connection each time instead of keeping a pool. Each test
# gets its own event loop, and pooled asyncpg connections can't move between loops.
test_engine = create_async_engine(TEST_DATABASE_URL, poolclass=NullPool)


@pytest.fixture(scope="session")
def anyio_backend():
    return "asyncio"


async def _recreate_test_database() -> None:
    # CREATE/DROP DATABASE can't run inside a transaction, so use a plain asyncpg
    # connection to the built-in "postgres" database.
    conn = await asyncpg.connect(
        user=TEST_DATABASE_URL.username,
        password=TEST_DATABASE_URL.password,
        host=TEST_DATABASE_URL.host,
        port=TEST_DATABASE_URL.port,
        database="postgres",
    )
    try:
        # The name comes from our own config, not user input, so building the SQL
        # string here is safe. These statements don't accept $1 parameters.
        name = TEST_DATABASE_URL.database
        await conn.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
        await conn.execute(f'CREATE DATABASE "{name}"')
    finally:
        await conn.close()


def _alembic_config() -> Config:
    """Alembic config pointed at the test database instead of the dev one."""
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    url = TEST_DATABASE_URL.render_as_string(hide_password=False)
    # Alembic's config file format treats % specially, so double it.
    cfg.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    return cfg


@pytest.fixture(scope="session")
def alembic_cfg() -> Config:
    return _alembic_config()


@pytest.fixture(scope="session", autouse=True)
def test_database(alembic_cfg):
    # Rebuilt from scratch every run, so the test database always matches the
    # migrations exactly, even after you edit one during development.
    asyncio.run(_recreate_test_database())
    command.upgrade(alembic_cfg, "head")


@pytest.fixture
async def db_session():
    """A session whose changes are all rolled back when the test ends.

    join_transaction_mode="create_savepoint" means code under test can call
    session.commit() normally: it only commits a savepoint inside our outer
    transaction, which we then roll back.
    """
    async with test_engine.connect() as conn:
        outer = await conn.begin()
        session = AsyncSession(
            bind=conn, join_transaction_mode="create_savepoint", expire_on_commit=False
        )
        try:
            yield session
        finally:
            await session.close()
            await outer.rollback()


@pytest.fixture
async def client(db_session):
    """HTTP client that calls the app in-process, using the test session."""

    async def override_get_session():
        yield db_session

    app.dependency_overrides[get_session] = override_get_session
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()
