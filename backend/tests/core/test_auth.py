from datetime import datetime, timedelta, timezone

import jwt
import pytest
from fastapi import HTTPException

from app.core.config import settings
from app.core.identity.deps import require_role
from tests.support import TEST_PASSWORD

pytestmark = pytest.mark.anyio


async def test_login_returns_a_token_that_works_on_me(client, make_user):
    user = await make_user(
        "director", "officer", email="dir@test.gm", positions=["director_of_trade"]
    )

    login = await client.post("/auth/login", json={"email": "DIR@test.gm", "password": TEST_PASSWORD})
    assert login.status_code == 200
    token = login.json()["access_token"]

    me = await client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200
    assert me.json() == {
        "id": user.id,
        "email": "dir@test.gm",
        "full_name": user.full_name,
        "roles": ["director", "officer"],
        "positions": ["director_of_trade"],
        "position_titles": ["Director of Trade"],
    }


async def test_wrong_password_and_unknown_email_look_the_same(client, make_user):
    await make_user(email="a@test.gm")

    wrong_password = await client.post("/auth/login", json={"email": "a@test.gm", "password": "nope"})
    unknown_email = await client.post("/auth/login", json={"email": "who@test.gm", "password": "nope"})

    assert wrong_password.status_code == unknown_email.status_code == 401
    assert wrong_password.json() == unknown_email.json()


async def test_deactivated_user_cannot_log_in_or_use_an_old_token(
    client, db_session, make_user, auth_headers
):
    user = await make_user(email="gone@test.gm")
    headers = auth_headers(user)

    user.is_active = False
    await db_session.commit()

    login = await client.post("/auth/login", json={"email": "gone@test.gm", "password": TEST_PASSWORD})
    assert login.status_code == 401
    assert (await client.get("/auth/me", headers=headers)).status_code == 401


async def test_me_without_token_is_401(client):
    response = await client.get("/auth/me")
    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"] == "Bearer"


@pytest.mark.parametrize(
    "token",
    [
        "not-a-jwt",
        # Expired an hour ago.
        jwt.encode(
            {"sub": "1", "exp": datetime.now(timezone.utc) - timedelta(hours=1)},
            settings.jwt_secret,
            algorithm="HS256",
        ),
        # Signed with someone else's secret: a forgery.
        jwt.encode({"sub": "1"}, "x" * 40, algorithm="HS256"),
    ],
    ids=["garbage", "expired", "forged"],
)
async def test_bad_tokens_are_401(client, token):
    response = await client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 401


async def test_require_role_allows_any_listed_role(make_user):
    director = await make_user("director")
    checker = require_role("minister", "director")
    assert await checker(user=director) is director


async def test_require_role_forbids_other_roles(make_user):
    applicant = await make_user("applicant")
    with pytest.raises(HTTPException) as exc:
        await require_role("admin")(user=applicant)
    assert exc.value.status_code == 403
