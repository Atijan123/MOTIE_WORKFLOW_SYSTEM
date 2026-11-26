"""Step 12b: staff work only through the staff app, applicants only through the
portal (app/core/identity/channel.py)."""

import pytest
from starlette.requests import Request

from app.core.config import Settings, settings
from app.core.identity.channel import read_channel
from tests.support import TEST_PASSWORD, TEST_PORTAL_KEYS, portal_headers

pytestmark = pytest.mark.anyio


@pytest.fixture
def bearer(auth_headers):
    """Just the token, without the portal headers auth_headers() adds."""

    async def _bearer(user) -> dict[str, str]:
        return {"Authorization": (await auth_headers(user))["Authorization"]}

    return _bearer


async def test_each_kind_of_user_works_through_its_own_portal_only(client, bearer, make_user):
    officer = await make_user("officer")
    applicant = await make_user("applicant")

    assert (await client.get("/auth/me", headers={**(await bearer(officer)), **portal_headers("staff")})).status_code == 200
    assert (await client.get("/auth/me", headers={**(await bearer(applicant)), **portal_headers("applicant")})).status_code == 200

    # A stolen staff token is no use from the public site, and the reverse.
    from_portal = await client.get("/auth/me", headers={**(await bearer(officer)), **portal_headers("applicant")})
    assert from_portal.status_code == 403
    assert from_portal.json()["detail"] == "Ministry staff sign in through the staff app."
    assert (await client.get("/auth/me", headers={**(await bearer(applicant)), **portal_headers("staff")})).status_code == 403


@pytest.mark.parametrize("key", [None, "", "not-the-key-but-long-enough-0123456789", TEST_PORTAL_KEYS["staff"] + "x"])
async def test_without_a_valid_portal_key_nothing_works(client, bearer, make_user, key):
    officer = await make_user("officer")
    headers = (await bearer(officer)) | ({"X-Portal-Key": key} if key is not None else {})
    assert (await client.get("/auth/me", headers=headers)).status_code == 403
    assert (await client.get("/cases/queue", headers=headers)).status_code == 403


async def test_a_staff_password_through_the_applicant_portal_looks_wrong(client, make_user):
    await make_user("officer", email="clerk@test.gm")
    through_portal = await client.post(
        "/auth/login", json={"email": "clerk@test.gm", "password": TEST_PASSWORD}, headers=portal_headers("applicant")
    )
    wrong_password = await client.post(
        "/auth/login", json={"email": "clerk@test.gm", "password": "wrong password!"}, headers=portal_headers("staff")
    )
    assert through_portal.status_code == wrong_password.status_code == 401
    assert through_portal.json() == wrong_password.json()


async def test_staff_routes_refuse_the_applicant_portals_domain(client, bearer, make_user, monkeypatch):
    monkeypatch.setattr(settings, "staff_portal_hosts", "staff.motie.test")
    monkeypatch.setattr(settings, "applicant_portal_hosts", "apply.motie.test, www.apply.motie.test")
    officer = await make_user("officer")

    async def via(host):
        return await client.get("/cases/queue", headers={**(await bearer(officer)), **portal_headers("staff", host=host)})

    assert (await via("staff.motie.test")).status_code == 200
    assert (await via("STAFF.motie.test:443")).status_code == 200  # case and port don't matter
    # Even with the staff app's key: the browser opened the public site's address.
    assert (await via("apply.motie.test")).status_code == 403
    assert (await via("www.apply.motie.test")).status_code == 403
    assert (await via("evil.example")).status_code == 403
    assert (await client.get("/cases/queue", headers={**(await bearer(officer)), **portal_headers("staff")})).status_code == 403


def _request(headers: dict[str, str], client_ip="172.18.0.5") -> Request:
    raw = [(k.lower().encode(), v.encode()) for k, v in headers.items()]
    return Request({"type": "http", "headers": raw, "client": (client_ip, 50000)})


def test_forwarded_headers_count_only_with_a_portal_key():
    forged = read_channel(_request({"X-Forwarded-Host": "staff.motie.test", "X-Client-IP": "10.1.2.3"}))
    assert (forged.portal, forged.host, forged.client_ip) == (None, None, "172.18.0.5")

    real = read_channel(_request(portal_headers("staff", host="staff.motie.test", ip="10.1.2.3")))
    assert (real.portal, real.host, real.client_ip) == ("staff", "staff.motie.test", "10.1.2.3")


def test_the_published_dev_keys_only_work_in_development():
    dev_key = "dev-staff-portal-key-not-a-secret-0000"
    base = dict(database_url="postgresql+asyncpg://x", jwt_secret="x" * 32, staff_portal_key=dev_key, _env_file=None)
    assert Settings(**base, app_env="development").portal_key("staff") == dev_key
    assert Settings(**base, app_env="production").portal_key("staff") is None
    assert Settings(**base, app_env="production", applicant_portal_key="").portal_key("applicant") is None
