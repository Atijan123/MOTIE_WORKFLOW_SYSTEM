"""Shared test setup.

Tests run against a separate database (<your db name>_test) so they never touch
dev data. Each test runs inside a transaction that is rolled back at the end, so
every test starts from the same clean state.

Three database users are involved, as in production:
- the Postgres superuser drops and recreates the test database;
- motie_owner runs the migrations, so it owns the tables;
- motie_app is what the code under test uses (db_session, client), so a
  missing GRANT fails a test instead of failing on the Ministry server.

Run the tests from the tools container, which has all three passwords:
`docker compose run --rm tools pytest -v`.

Async tests use the anyio pytest plugin, which ships with FastAPI's dependencies:
mark a test module with `pytestmark = pytest.mark.anyio`.
"""

import asyncio
import itertools
import os
from contextlib import asynccontextmanager
from pathlib import Path

import asyncpg
import pytest
from alembic import command
from alembic.config import Config
from httpx import ASGITransport, AsyncClient
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import DEV_REGISTRY_REFERENCE, settings
from app.core.identity.security import create_access_token
from app.core.identity.service import assign_position, create_user
from app.db.session import get_session
from app.main import app
from tests.support import STAFF, TEST_PASSWORD

BACKEND_DIR = Path(__file__).resolve().parent.parent

if not settings.migration_database_url:
    raise RuntimeError("Tests need MIGRATION_DATABASE_URL. Run: docker compose run --rm tools pytest")

_dev_url = make_url(settings.database_url)
TEST_DATABASE_URL = _dev_url.set(database=f"{_dev_url.database}_test")
TEST_OWNER_URL = make_url(settings.migration_database_url).set(database=TEST_DATABASE_URL.database)

# NullPool: open a fresh connection each time instead of keeping a pool. Each test
# gets its own event loop, and pooled asyncpg connections can't move between loops.
test_engine = create_async_engine(TEST_DATABASE_URL, poolclass=NullPool)
owner_engine = create_async_engine(TEST_OWNER_URL, poolclass=NullPool)


@pytest.fixture(scope="session")
def anyio_backend():
    return "asyncio"


async def recreate_database(name: str) -> None:
    # CREATE/DROP DATABASE can't run inside a transaction, so use a plain asyncpg
    # connection to the built-in "postgres" database, as the superuser: the
    # owner and app users aren't allowed to create databases.
    conn = await asyncpg.connect(
        user=os.environ["POSTGRES_USER"],
        password=os.environ["POSTGRES_PASSWORD"],
        host=TEST_DATABASE_URL.host,
        port=TEST_DATABASE_URL.port,
        database="postgres",
    )
    try:
        # The name comes from our own config, not user input, so building the SQL
        # string here is safe. These statements don't accept $1 parameters.
        await conn.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
        await conn.execute(f'CREATE DATABASE "{name}" OWNER {TEST_OWNER_URL.username}')
    finally:
        await conn.close()


def alembic_config(database: str) -> Config:
    """Alembic config pointed at a test database instead of the dev one."""
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    url = TEST_OWNER_URL.set(database=database).render_as_string(hide_password=False)
    # Alembic's config file format treats % specially, so double it.
    cfg.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    return cfg


@pytest.fixture(scope="session", autouse=True)
def test_database():
    # Rebuilt from scratch every run, so the test database always matches the
    # migrations exactly, even after you edit one during development.
    asyncio.run(recreate_database(TEST_DATABASE_URL.database))
    command.upgrade(alembic_config(TEST_DATABASE_URL.database), "head")


@pytest.fixture(autouse=True)
def document_storage(tmp_path, monkeypatch):
    """Every test stores uploads in its own temporary folder, never the real volume."""
    monkeypatch.setattr(settings, "document_storage_dir", str(tmp_path / "documents"))
    return tmp_path / "documents"


@pytest.fixture(autouse=True)
def registry_reference(monkeypatch):
    """Letters can be signed whatever APP_ENV your .env says: without a
    reference set, a production server blocks signing (test_registry_reference.py)."""
    monkeypatch.setattr(settings, "facility_letter_reference_format", DEV_REGISTRY_REFERENCE)


@pytest.fixture
def empty_database_config() -> Config:
    """Alembic config for a fresh, empty database of its own (for the downgrade test)."""
    name = f"{TEST_DATABASE_URL.database}_migrations"
    asyncio.run(recreate_database(name))
    return alembic_config(name)


@pytest.fixture
def committing_engine():
    """For the rare test that needs real commits on several connections (e.g. a race).

    Data it commits stays until the next run rebuilds the test database, so such
    tests must use their own unique emails and must not count rows globally.
    """
    return test_engine


@asynccontextmanager
async def _rolled_back_session(engine):
    async with engine.connect() as conn:
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
async def db_session():
    """A session, logged in as motie_app, whose changes are all rolled back when the test ends.

    join_transaction_mode="create_savepoint" means code under test can call
    session.commit() normally: it only commits a savepoint inside our outer
    transaction, which we then roll back.
    """
    async with _rolled_back_session(test_engine) as session:
        yield session


@pytest.fixture
async def owner_session():
    """Like db_session but logged in as motie_owner, for tests that must write
    tables the app may only read (e.g. workflow definitions) or that check what
    the owner can and can't do. Also rolled back.

    It's a separate connection, so it can't see db_session's uncommitted rows.
    """
    async with _rolled_back_session(owner_engine) as session:
        yield session


@pytest.fixture
def make_user(db_session):
    """Create users in the test database: `officer = await make_user("officer")`.

    `positions=["trade_officer"]` also makes them a holder of those posts.
    """
    numbers = itertools.count(1)

    async def _make(*role_codes: str, email: str | None = None, positions: tuple[str, ...] = ()):
        n = next(numbers)
        user = await create_user(
            db_session,
            email=email or f"user{n}@test.gm",
            full_name=f"Test User {n}",
            password=TEST_PASSWORD,
            role_codes=list(role_codes),
        )
        for code in positions:
            await assign_position(db_session, user=user, position_code=code, actor=None)
        return user

    return _make


@pytest.fixture
def auth_headers():
    """Headers that log a request in as `user`: `client.get(..., headers=auth_headers(user))`."""

    def _headers(user) -> dict[str, str]:
        return {"Authorization": f"Bearer {create_access_token(user.id)}"}

    return _headers


@pytest.fixture
async def client(db_session):
    """HTTP client that calls the app in-process, using the test session."""

    async def override_get_session():
        yield db_session

    app.dependency_overrides[get_session] = override_get_session
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
async def people(make_user):
    """The applicant plus one user per post in the ETLS chain."""
    users = {"applicant": await make_user("applicant")}
    for key, (role, position) in STAFF.items():
        users[key] = await make_user(role, positions=[position])
    return users


@pytest.fixture
def act(client, auth_headers):
    """Shortcut: `await act(user, "post", "/cases/1/status", json=...)`."""

    async def _act(user, method, url, headers_extra=None, **kwargs):
        headers = {**auth_headers(user), **(headers_extra or {})}
        return await getattr(client, method)(url, headers=headers, **kwargs)

    return _act
