"""Shared test setup.

Tests run against a separate database (<your db name>_test) so they never touch
dev data. Each test runs inside a transaction that is rolled back at the end, so
every test starts from the same clean state.

Async tests use the anyio pytest plugin, which ships with FastAPI's dependencies:
mark a test module with `pytestmark = pytest.mark.anyio`.
"""

import asyncio

import asyncpg
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import settings
from app.db.session import get_session
from app.main import app

_dev_url = make_url(settings.database_url)
TEST_DATABASE_URL = _dev_url.set(database=f"{_dev_url.database}_test")

# NullPool: open a fresh connection each time instead of keeping a pool. Each test
# gets its own event loop, and pooled asyncpg connections can't move between loops.
test_engine = create_async_engine(TEST_DATABASE_URL, poolclass=NullPool)


@pytest.fixture(scope="session")
def anyio_backend():
    return "asyncio"


async def _create_test_database() -> None:
    # CREATE DATABASE can't run inside a transaction, so use a plain asyncpg
    # connection to the built-in "postgres" database.
    conn = await asyncpg.connect(
        user=TEST_DATABASE_URL.username,
        password=TEST_DATABASE_URL.password,
        host=TEST_DATABASE_URL.host,
        port=TEST_DATABASE_URL.port,
        database="postgres",
    )
    try:
        exists = await conn.fetchval(
            "SELECT 1 FROM pg_database WHERE datname = $1", TEST_DATABASE_URL.database
        )
        if not exists:
            # The name comes from our own config, not user input, so building the
            # SQL string here is safe. CREATE DATABASE doesn't accept $1 parameters.
            await conn.execute(f'CREATE DATABASE "{TEST_DATABASE_URL.database}"')
    finally:
        await conn.close()


@pytest.fixture(scope="session", autouse=True)
def test_database():
    asyncio.run(_create_test_database())


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
