"""Step 12c: staff work only from the networks in STAFF_IP_ALLOWLIST."""

import pytest
from pydantic import ValidationError

from app.core.config import Settings, settings
from tests.support import TEST_PASSWORD, portal_headers

pytestmark = pytest.mark.anyio

OFFICE = "10.20.0.0/16, 196.46.1.7"


@pytest.fixture
def allowlist_on(monkeypatch):
    monkeypatch.setattr(settings, "staff_ip_allowlist_enabled", True)
    monkeypatch.setattr(settings, "staff_ip_allowlist", OFFICE)


@pytest.fixture
def as_staff(auth_headers):
    async def _as_staff(user, ip=None):
        extra = {"ip": ip} if ip else {}
        return {**(await auth_headers(user)), **portal_headers("staff", **extra)}

    return _as_staff


@pytest.mark.parametrize(
    ("ip", "allowed"),
    [
        ("10.20.4.9", True),  # in the office range
        ("196.46.1.7", True),  # the one VPN address
        ("::ffff:10.20.4.9", True),  # the same IPv4 address, written as IPv6
        ("10.21.0.1", False),
        ("196.46.1.8", False),
        ("8.8.8.8", False),
        ("not-an-ip", False),
        (None, False),  # unknown IP: refused while the check is on
    ],
)
async def test_staff_requests_only_from_the_allowed_networks(client, make_user, allowlist_on, as_staff, ip, allowed):
    officer = await make_user("officer")
    response = await client.get("/cases/queue", headers=await as_staff(officer, ip))
    assert response.status_code == (200 if allowed else 403)
    if not allowed:
        assert response.json()["detail"] == "The staff app works only on the Ministry network or VPN."


async def test_the_staff_login_is_refused_from_outside_before_the_password_is_checked(
    client, make_user, allowlist_on
):
    await make_user("officer", email="clerk@test.gm")
    outside = portal_headers("staff", ip="8.8.8.8")
    right = await client.post("/auth/login", json={"email": "clerk@test.gm", "password": TEST_PASSWORD}, headers=outside)
    wrong = await client.post("/auth/login", json={"email": "clerk@test.gm", "password": "nope nope"}, headers=outside)
    # The same answer either way: from outside, the login can't test a password.
    assert right.status_code == wrong.status_code == 403
    assert right.json() == wrong.json()

    inside = portal_headers("staff", ip="10.20.0.5")
    ok = await client.post("/auth/login", json={"email": "clerk@test.gm", "password": TEST_PASSWORD}, headers=inside)
    assert ok.status_code == 200


async def test_applicants_are_not_limited_to_the_ministry_network(client, make_user, auth_headers, allowlist_on):
    applicant = await make_user("applicant")
    headers = {**(await auth_headers(applicant)), **portal_headers("applicant", ip="8.8.8.8")}
    assert (await client.get("/auth/me", headers=headers)).status_code == 200


async def test_on_with_an_empty_list_lets_no_staff_in(client, make_user, monkeypatch, as_staff):
    monkeypatch.setattr(settings, "staff_ip_allowlist_enabled", True)
    monkeypatch.setattr(settings, "staff_ip_allowlist", "")
    officer = await make_user("officer")
    assert (await client.get("/auth/me", headers=await as_staff(officer, "10.20.0.5"))).status_code == 403


def test_on_by_default_except_in_development():
    base = dict(database_url="postgresql+asyncpg://x", jwt_secret="x" * 32, _env_file=None)
    assert Settings(**base, app_env="production").staff_ip_check_on() is True
    assert Settings(**base, app_env="development").staff_ip_check_on() is False
    # Can be switched on in development to try it, or off on a server (not advised).
    assert Settings(**base, app_env="development", staff_ip_allowlist_enabled=True).staff_ip_check_on() is True


def test_a_typo_in_the_list_stops_the_server_starting():
    with pytest.raises(ValidationError, match="not an IP address or range"):
        Settings(database_url="postgresql+asyncpg://x", jwt_secret="x" * 32, staff_ip_allowlist="10.20.0.0/16, 10.20.0.x", _env_file=None)


def test_a_blank_setting_from_compose_means_the_default():
    # docker-compose.yml passes STAFF_IP_ALLOWLIST_ENABLED="" when .env leaves it out.
    s = Settings(database_url="postgresql+asyncpg://x", jwt_secret="x" * 32, staff_ip_allowlist_enabled="", app_env="production", _env_file=None)
    assert s.staff_ip_check_on() is True
