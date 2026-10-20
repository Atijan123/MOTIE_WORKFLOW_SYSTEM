"""The development seed (app/dev_seed.py), which scripts/reset-dev.sh runs."""

import pytest

from app import dev_seed
from app.core.config import Settings, settings
from app.core.identity.service import get_user_by_email

pytestmark = pytest.mark.anyio


async def test_seed_creates_one_user_per_post_and_twice_changes_nothing(db_session):
    created = await dev_seed.seed(db_session, "a dev password 1")
    assert created == [email for email, *_ in dev_seed.USERS]

    desk = await get_user_by_email(db_session, "desk@motie.test")
    assert desk.position_codes == {"etls_desk_officer"}
    ps = await get_user_by_email(db_session, "ps@motie.test")
    assert ps.position_codes == {"permanent_secretary"}

    assert await dev_seed.seed(db_session, "a dev password 1") == []


async def test_seeded_users_can_log_in(db_session, client):
    await dev_seed.seed(db_session, "a dev password 1")
    response = await client.post("/auth/login", json={"email": "records@motie.test", "password": "a dev password 1"})
    assert response.status_code == 200


def test_the_seed_refuses_to_run_outside_development(monkeypatch):
    monkeypatch.setattr(settings, "app_env", "production")
    with pytest.raises(SystemExit, match="Refusing"):
        dev_seed.main()


def test_app_env_defaults_to_production(monkeypatch):
    # A server that forgets to set it must not count as a dev machine.
    monkeypatch.delenv("APP_ENV", raising=False)
    assert Settings(_env_file=None).app_env == "production"
