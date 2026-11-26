"""Step 12d: account lockout, per-IP rate limiting, and every login audited
(app/core/identity/login_guard.py)."""

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError

from app.core.audit.models import AuditEvent
from app.core.config import settings
from app.core.identity.models import LoginAttempt
from tests.support import TEST_PASSWORD, portal_headers

pytestmark = pytest.mark.anyio

WRONG = "not the password"


@pytest.fixture
def login(client):
    async def _login(email, password, *, portal="applicant", ip=None):
        extra = {"ip": ip} if ip else {}
        return await client.post(
            "/auth/login", json={"email": email, "password": password}, headers=portal_headers(portal, **extra)
        )

    return _login


async def test_five_failures_lock_the_account_even_against_the_right_password(login, make_user):
    await make_user(email="amie@test.gm")
    for _ in range(5):
        assert (await login("amie@test.gm", WRONG)).status_code == 401

    locked = await login("amie@test.gm", TEST_PASSWORD)
    assert locked.status_code == 429
    assert locked.json()["detail"].startswith("Too many failed attempts: this account is locked.")
    assert "15 minutes" in locked.json()["detail"]
    assert locked.headers["Retry-After"] == str(15 * 60)


async def test_four_failures_dont_lock(login, make_user):
    await make_user(email="amie@test.gm")
    for _ in range(4):
        await login("amie@test.gm", WRONG)
    assert (await login("amie@test.gm", TEST_PASSWORD)).status_code == 200


async def test_failures_before_a_successful_login_dont_count(login, make_user):
    await make_user(email="amie@test.gm")
    for _ in range(4):
        await login("amie@test.gm", WRONG)
    assert (await login("amie@test.gm", TEST_PASSWORD)).status_code == 200
    for _ in range(4):
        await login("amie@test.gm", WRONG)
    assert (await login("amie@test.gm", TEST_PASSWORD)).status_code == 200


async def test_the_lock_ends_when_the_failures_are_older_than_the_window(login, make_user, db_session):
    await make_user(email="amie@test.gm")
    long_ago = datetime.now(timezone.utc) - timedelta(minutes=16)
    db_session.add_all(
        LoginAttempt(email="amie@test.gm", outcome="bad_password", attempted_at=long_ago) for _ in range(5)
    )
    await db_session.commit()
    assert (await login("amie@test.gm", TEST_PASSWORD)).status_code == 200


async def test_knocking_on_a_locked_account_doesnt_keep_it_locked(login, make_user, db_session):
    await make_user(email="amie@test.gm")
    for _ in range(5):
        await login("amie@test.gm", WRONG)
    for _ in range(3):
        assert (await login("amie@test.gm", WRONG)).status_code == 429
    outcomes = (await db_session.scalars(select(LoginAttempt.outcome).where(LoginAttempt.email == "amie@test.gm"))).all()
    # The refused tries are recorded, but as "refused": they don't count.
    assert sorted(outcomes) == ["bad_password"] * 5 + ["refused"] * 3


async def test_an_unknown_email_locks_the_same_way(login, make_user):
    """So "locked" doesn't reveal whether an account exists."""
    await make_user(email="amie@test.gm")
    for email in ("amie@test.gm", "nobody@test.gm"):
        for _ in range(5):
            await login(email, WRONG)
    real, unknown = await login("amie@test.gm", WRONG), await login("nobody@test.gm", WRONG)
    assert real.status_code == unknown.status_code == 429
    assert real.json() == unknown.json()


async def test_a_staff_password_through_the_portal_counts_as_a_failure(login, make_user):
    """Otherwise five such tries without a lock would reveal the password was right."""
    await make_user("officer", email="clerk@test.gm")
    for _ in range(5):
        assert (await login("clerk@test.gm", TEST_PASSWORD, portal="applicant")).status_code == 401
    assert (await login("clerk@test.gm", TEST_PASSWORD, portal="staff")).status_code == 429


async def test_one_ip_is_limited_across_all_accounts(login, make_user, monkeypatch):
    monkeypatch.setattr(settings, "login_ip_limit", 5)
    await make_user(email="amie@test.gm")
    for n in range(5):
        await login(f"guess{n}@test.gm", WRONG, ip="41.223.1.9")

    limited = await login("amie@test.gm", TEST_PASSWORD, ip="41.223.1.9")
    assert limited.status_code == 429
    assert limited.json()["detail"] == "Too many sign-in attempts from this network. Try again in a few minutes."
    # Another IP isn't affected.
    assert (await login("amie@test.gm", TEST_PASSWORD, ip="41.223.1.10")).status_code == 200


async def test_every_login_and_failure_is_in_the_audit_log(login, make_user, db_session):
    user = await make_user(email="amie@test.gm")
    await login("amie@test.gm", WRONG, ip="41.223.1.9")
    await login("nobody@test.gm", WRONG, ip="41.223.1.9")
    await login("amie@test.gm", TEST_PASSWORD, ip="41.223.1.9")

    events = (
        await db_session.scalars(
            select(AuditEvent).where(AuditEvent.action.like("auth.login_%")).order_by(AuditEvent.id)
        )
    ).all()
    assert [(e.action, e.entity_type, e.entity_id, e.actor_user_id) for e in events] == [
        ("auth.login_failed", "login", "amie@test.gm", None),  # wrong password: no user is named
        ("auth.login_failed", "login", "nobody@test.gm", None),
        ("auth.login_succeeded", "user", str(user.id), user.id),
    ]
    assert events[0].details == {"outcome": "bad_password", "portal": "applicant", "ip": "41.223.1.9"}


async def test_a_staff_password_on_the_portal_is_audited_against_the_account(login, make_user, db_session):
    officer = await make_user("officer", email="clerk@test.gm")
    await login("clerk@test.gm", TEST_PASSWORD, portal="applicant")
    event = await db_session.scalar(select(AuditEvent).where(AuditEvent.action == "auth.login_failed"))
    assert (event.entity_type, event.entity_id, event.details["outcome"]) == ("user", str(officer.id), "wrong_portal")


@pytest.mark.parametrize(
    "statement",
    ["UPDATE core.login_attempts SET outcome = 'success'", "DELETE FROM core.login_attempts"],
    ids=["update", "delete"],
)
async def test_the_app_cannot_rewrite_or_erase_attempts(db_session, statement):
    with pytest.raises(DBAPIError, match="permission denied"):
        await db_session.execute(text(statement))


async def test_huge_inputs_are_refused_before_hashing(client):
    response = await client.post(
        "/auth/login", json={"email": "a@test.gm", "password": "x" * 5000}, headers=portal_headers("applicant")
    )
    assert response.status_code == 422
