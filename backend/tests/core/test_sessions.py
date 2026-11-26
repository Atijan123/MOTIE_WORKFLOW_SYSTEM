"""Step 12f: sessions on the server. Staff are signed out after 30 minutes idle
and 8 hours in all; signing a letter asks for the password again after 10
minutes (app/core/identity/sessions.py, needs_recent_password in 0045)."""

from datetime import datetime, timedelta, timezone

import jwt
import pytest
from sqlalchemy import select

from app.core.config import settings
from app.core.identity import sessions
from app.core.identity.models import LoginSession
from app.core.identity.security import create_access_token
from app.core.workflow.models import WorkflowStatus, WorkflowTransition
from tests.support import TEST_PASSWORD, move, portal_headers, verified_case

pytestmark = pytest.mark.anyio


async def _session_of(db_session, headers) -> LoginSession:
    token = headers["Authorization"].removeprefix("Bearer ")
    sid = jwt.decode(token, settings.jwt_secret, algorithms=["HS256"])["sid"]
    return await db_session.get(LoginSession, sid)


def _ago(**delta) -> datetime:
    return datetime.now(timezone.utc) - timedelta(**delta)


async def test_staff_are_signed_out_after_30_minutes_idle(client, make_user, auth_headers, db_session):
    officer = await make_user("officer")
    headers = await auth_headers(officer)
    row = await _session_of(db_session, headers)
    row.last_seen_at = _ago(minutes=29)
    await db_session.commit()
    assert (await client.get("/auth/me", headers=headers)).status_code == 200  # 29 minutes: still in

    row.last_seen_at = _ago(minutes=31)
    await db_session.commit()
    assert (await client.get("/auth/me", headers=headers)).status_code == 401
    await db_session.refresh(row)
    assert row.ended_reason == "idle"
    # Ended for good: coming back doesn't revive it.
    assert (await client.get("/auth/me", headers=headers)).status_code == 401


async def test_each_request_keeps_the_session_alive(client, make_user, auth_headers, db_session):
    officer = await make_user("officer")
    headers = await auth_headers(officer)
    row = await _session_of(db_session, headers)
    row.last_seen_at = _ago(minutes=20)
    await db_session.commit()
    await client.get("/auth/me", headers=headers)
    await db_session.refresh(row)
    assert row.last_seen_at > _ago(minutes=1)


async def test_staff_are_signed_out_8_hours_after_signing_in_however_busy(client, make_user, auth_headers, db_session):
    officer = await make_user("officer")
    row = await _session_of(db_session, await auth_headers(officer))
    assert row.expires_at - row.created_at == timedelta(hours=8)

    # A session that began just over 8 hours ago, busy all day (last seen just
    # now). The app may not move a session's end (only its owner can), so the
    # test makes one that started then, with a token that is itself still valid.
    started = _ago(hours=8, seconds=1)
    db_session.add(LoginSession(
        id="started-this-morning", user_id=officer.id, portal="staff", created_at=started,
        last_seen_at=_ago(seconds=5), expires_at=started + timedelta(hours=8), password_checked_at=started,
    ))
    await db_session.commit()
    token = create_access_token(officer.id, "started-this-morning", datetime.now(timezone.utc) + timedelta(hours=1))
    response = await client.get("/auth/me", headers={"Authorization": f"Bearer {token}", **portal_headers("staff")})
    assert response.status_code == 401


async def test_applicants_have_no_idle_limit_and_keep_their_hour(client, make_user, auth_headers, db_session):
    applicant = await make_user("applicant")
    headers = await auth_headers(applicant)
    row = await _session_of(db_session, headers)
    assert row.expires_at - row.created_at == timedelta(minutes=settings.access_token_minutes)
    row.last_seen_at = _ago(minutes=45)
    await db_session.commit()
    assert (await client.get("/auth/me", headers=headers)).status_code == 200


async def test_signing_out_ends_the_session_on_the_server(client, make_user, auth_headers):
    officer = await make_user("officer")
    headers = await auth_headers(officer)
    assert (await client.post("/auth/logout", headers=headers)).status_code == 204
    # A copy of the token is useless now, not only the deleted cookie.
    assert (await client.get("/auth/me", headers=headers)).status_code == 401


async def test_a_token_without_a_session_is_refused(client, make_user):
    officer = await make_user("officer")
    # The shape tokens had before step 12f: no "sid".
    old = jwt.encode(
        {"sub": str(officer.id), "typ": "access", "exp": datetime.now(timezone.utc) + timedelta(hours=1)},
        settings.jwt_secret, algorithm="HS256",
    )
    response = await client.get("/auth/me", headers={"Authorization": f"Bearer {old}", **portal_headers("staff")})
    assert response.status_code == 401
    made_up = jwt.encode(
        {"sub": str(officer.id), "sid": "no-such-session", "typ": "access", "exp": datetime.now(timezone.utc) + timedelta(hours=1)},
        settings.jwt_secret, algorithm="HS256",
    )
    response = await client.get("/auth/me", headers={"Authorization": f"Bearer {made_up}", **portal_headers("staff")})
    assert response.status_code == 401


async def test_someone_elses_session_id_doesnt_work(client, make_user, auth_headers, db_session):
    a, b = await make_user("officer"), await make_user("officer")
    row = await _session_of(db_session, await auth_headers(a))
    forged = jwt.encode(
        {"sub": str(b.id), "sid": row.id, "typ": "access", "exp": datetime.now(timezone.utc) + timedelta(hours=1)},
        settings.jwt_secret, algorithm="HS256",
    )
    assert (await client.get("/auth/me", headers={"Authorization": f"Bearer {forged}", **portal_headers("staff")})).status_code == 401


# --- Asking for the password again before signing --------------------------------------


async def test_only_signing_and_approving_need_a_recent_password(db_session):
    guarded = (
        await db_session.execute(
            select(WorkflowStatus.code)
            .join(WorkflowTransition, WorkflowTransition.to_status_id == WorkflowStatus.id)
            .where(WorkflowTransition.needs_recent_password)
        )
    ).scalars().all()
    assert sorted(set(guarded)) == ["approved", "signed"]


async def test_signing_asks_for_the_password_again_after_10_minutes(client, act, people, auth_headers, db_session):
    case_id = await verified_case(act, people)
    director = people["director"]
    headers = await auth_headers(director)
    row = await _session_of(db_session, headers)
    row.password_checked_at = _ago(minutes=11)
    await db_session.commit()

    sign = {"to_status": "signed"}
    actions = (await client.get(f"/cases/{case_id}", headers=headers)).json()["available_actions"]
    assert [a["needs_recent_password"] for a in actions if a["to_status"] == "signed"] == [True]
    refused = await client.post(f"/cases/{case_id}/status", json=sign, headers=headers)
    assert refused.status_code == 403
    assert "needs your password" in refused.json()["detail"]

    status = (await client.get("/auth/session", headers=headers)).json()
    assert datetime.fromisoformat(status["password_fresh_until"]) < datetime.now(timezone.utc)
    assert status["idle_minutes"] == 30

    wrong = await client.post("/auth/reauth", json={"password": "not it at all"}, headers=headers)
    assert wrong.status_code == 401
    assert (await client.post(f"/cases/{case_id}/status", json=sign, headers=headers)).status_code == 403

    right = await client.post("/auth/reauth", json={"password": TEST_PASSWORD}, headers=headers)
    assert right.status_code == 200
    assert (await client.post(f"/cases/{case_id}/status", json=sign, headers=headers)).status_code == 200


async def test_a_recent_password_needs_no_second_typing(act, people):
    # Signed in a moment ago (auth_headers starts a fresh session): the password is recent.
    case_id = await verified_case(act, people)
    assert (await move(act, people["director"], case_id, "signed")).status_code == 200


async def test_wrong_passwords_at_the_recheck_count_towards_the_lockout(client, make_user, auth_headers):
    officer = await make_user("officer")
    headers = await auth_headers(officer)
    for _ in range(5):
        assert (await client.post("/auth/reauth", json={"password": "wrong wrong"}, headers=headers)).status_code == 401
    assert (await client.post("/auth/reauth", json={"password": TEST_PASSWORD}, headers=headers)).status_code == 429


def test_the_times_are_settings():
    assert (settings.staff_idle_minutes, settings.staff_session_hours, settings.reauth_minutes) == (30, 8, 10)
    assert sessions.TOUCH_EVERY == timedelta(seconds=60)
