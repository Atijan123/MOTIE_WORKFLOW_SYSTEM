import pytest

from app.db.session import get_session
from app.main import app

pytestmark = pytest.mark.anyio


async def test_health_ok(client):
    response = await client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


async def test_health_db_ok(client):
    response = await client.get("/health/db")
    assert response.status_code == 200
    assert response.json() == {"database": "ok"}


class _BrokenSession:
    """Stands in for a session whose database is unreachable."""

    async def execute(self, *args, **kwargs):
        raise OSError("could not connect to db:5432 as user motie")


async def test_health_db_down_returns_503_without_leaking_details(client):
    async def broken_session():
        yield _BrokenSession()

    app.dependency_overrides[get_session] = broken_session

    response = await client.get("/health/db")

    assert response.status_code == 503
    assert response.json() == {"database": "unavailable"}
    assert "motie" not in response.text
