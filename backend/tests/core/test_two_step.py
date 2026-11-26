"""Step 12e: two-step login for staff (app/core/identity/totp.py, two_step.py, router.py)."""

import base64
from datetime import datetime, timedelta, timezone

import jwt
import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError

from app.core.audit.models import AuditEvent
from app.core.config import settings
from app.core.identity import totp
from app.core.identity.models import TotpCredential
from tests.support import TEST_PASSWORD, portal_headers, sign_in_staff

pytestmark = pytest.mark.anyio

STAFF = portal_headers("staff")

# --- The code itself: RFC 6238's own test values -------------------------------------

# Appendix B of RFC 6238 uses the ASCII secret "12345678901234567890" and
# 8-digit codes; authenticator apps show the last 6 digits.
RFC_SECRET = base64.b32encode(b"12345678901234567890").decode()


@pytest.mark.parametrize(
    ("unix_time", "eight_digits"),
    [(59, "94287082"), (1111111109, "07081804"), (1111111111, "14050471"), (1234567890, "89005924"),
     (2000000000, "69279037"), (20000000000, "65353130")],
)
def test_codes_match_the_rfc_test_vectors(unix_time, eight_digits):
    assert totp.code_at(RFC_SECRET, totp.current_step(unix_time)) == eight_digits[-6:]


def test_a_code_works_for_a_step_either_side_and_only_once():
    now = 1_700_000_000.0
    step = totp.current_step(now)
    assert totp.matching_step(RFC_SECRET, totp.code_at(RFC_SECRET, step - 1), now=now) == step - 1
    assert totp.matching_step(RFC_SECRET, totp.code_at(RFC_SECRET, step + 1), now=now) == step + 1
    assert totp.matching_step(RFC_SECRET, totp.code_at(RFC_SECRET, step - 2), now=now) is None
    # Already used to sign in: refused, even though it is the right code.
    assert totp.matching_step(RFC_SECRET, totp.code_at(RFC_SECRET, step), after_step=step, now=now) is None
    assert totp.matching_step(RFC_SECRET, "12345", now=now) is None
    assert totp.matching_step(RFC_SECRET, "abcdef", now=now) is None


def test_the_setup_link_is_what_authenticator_apps_read():
    uri = totp.provisioning_uri("ABC234", account="desk@motie.gov.gm", issuer="MOTIE ETLS")
    assert uri == ("otpauth://totp/MOTIE%20ETLS%3Adesk%40motie.gov.gm?secret=ABC234&issuer=MOTIE+ETLS"
                   "&algorithm=SHA1&digits=6&period=30")


# --- Signing in ---------------------------------------------------------------------


async def _password(client, user):
    response = await client.post("/auth/login", json={"email": user.email, "password": TEST_PASSWORD}, headers=STAFF)
    assert response.status_code == 200, response.text
    return response.json()


async def _set_up(client, user) -> tuple[str, list[str]]:
    """First sign-in; returns (the authenticator secret, the recovery codes)."""
    challenge = (await _password(client, user))["challenge"]
    secret = (await client.post("/auth/two-step/set-up", json={"challenge": challenge}, headers=STAFF)).json()["secret"]
    done = await client.post(
        "/auth/two-step/confirm", json={"challenge": challenge, "code": totp.code_at(secret, totp.current_step())}, headers=STAFF
    )
    return secret, done.json()["recovery_codes"]


async def _code_login(client, user, code):
    challenge = (await _password(client, user))["challenge"]
    return await client.post("/auth/login/code", json={"challenge": challenge, "code": code}, headers=STAFF)


async def test_a_staff_password_alone_gives_no_session(client, make_user):
    officer = await make_user("officer")
    answer = await _password(client, officer)
    assert answer["next"] == "set_up" and answer["access_token"] is None
    # The challenge is not a login.
    me = await client.get("/auth/me", headers={"Authorization": f"Bearer {answer['challenge']}", **STAFF})
    assert me.status_code == 401


async def test_applicants_still_sign_in_with_a_password(client, make_user):
    applicant = await make_user("applicant")
    answer = await client.post(
        "/auth/login", json={"email": applicant.email, "password": TEST_PASSWORD}, headers=portal_headers("applicant")
    )
    assert answer.json()["next"] == "done" and answer.json()["access_token"]


async def test_the_first_sign_in_sets_up_an_authenticator_and_gives_recovery_codes(client, make_user, db_session):
    officer = await make_user("officer")
    challenge = (await _password(client, officer))["challenge"]
    start = (await client.post("/auth/two-step/set-up", json={"challenge": challenge}, headers=STAFF)).json()
    assert start["otpauth_uri"].startswith("otpauth://totp/") and start["qr_svg"].startswith("<?xml")

    wrong = await client.post("/auth/two-step/confirm", json={"challenge": challenge, "code": "000000"}, headers=STAFF)
    assert wrong.status_code == 401

    code = totp.code_at(start["secret"], totp.current_step())
    done = await client.post("/auth/two-step/confirm", json={"challenge": challenge, "code": code}, headers=STAFF)
    assert done.status_code == 200
    assert done.json()["access_token"]
    codes = done.json()["recovery_codes"]
    assert len(codes) == 10 and len(set(codes)) == 10

    # Stored encrypted: the secret isn't in the row as written.
    row = await db_session.get(TotpCredential, officer.id)
    assert start["secret"] not in row.secret_encrypted
    assert "auth.two_step_set_up" in (await db_session.scalars(select(AuditEvent.action))).all()


async def test_someone_with_the_password_cant_replace_a_set_up_authenticator(client, make_user):
    officer = await make_user("officer")
    await _set_up(client, officer)
    answer = await _password(client, officer)
    assert answer["next"] == "code"
    again = await client.post("/auth/two-step/set-up", json={"challenge": answer["challenge"]}, headers=STAFF)
    assert again.status_code == 409


async def test_a_code_signs_in_once(client, make_user):
    officer = await make_user("officer")
    secret, _ = await _set_up(client, officer)
    # Setting up used this step's code; the next step's is accepted (clock drift allowance).
    code = totp.code_at(secret, totp.current_step() + 1)
    assert (await _code_login(client, officer, code)).status_code == 200
    replay = await _code_login(client, officer, code)
    assert replay.status_code == 401
    assert "didn't work" in replay.json()["detail"]


async def test_wrong_codes_count_towards_the_lockout(client, make_user):
    officer = await make_user("officer")
    await _set_up(client, officer)
    for _ in range(5):
        assert (await _code_login(client, officer, "000000")).status_code == 401
    # Locked now, even at the password step.
    locked = await client.post("/auth/login", json={"email": officer.email, "password": TEST_PASSWORD}, headers=STAFF)
    assert locked.status_code == 429


async def test_a_recovery_code_works_once(client, make_user, db_session):
    officer = await make_user("officer")
    _, codes = await _set_up(client, officer)

    async def with_recovery(code):
        challenge = (await _password(client, officer))["challenge"]
        return await client.post("/auth/login/recovery-code", json={"challenge": challenge, "code": code}, headers=STAFF)

    # Typed in lower case, without the dash: still accepted.
    assert (await with_recovery(codes[0].lower().replace("-", ""))).status_code == 200
    assert (await with_recovery(codes[0])).status_code == 401
    event = await db_session.scalar(select(AuditEvent).where(AuditEvent.action == "auth.recovery_code_used"))
    assert event.details == {"codes_left": 9}


async def test_new_recovery_codes_need_a_current_code_and_replace_the_old_ones(client, make_user, monkeypatch):
    officer = await make_user("officer")
    secret, old = await _set_up(client, officer)
    token = (await _code_login(client, officer, totp.code_at(secret, totp.current_step() + 1))).json()["access_token"]
    signed_in = {"Authorization": f"Bearer {token}", **STAFF}
    assert (await client.get("/auth/two-step", headers=signed_in)).json() == {"set_up": True, "recovery_codes_left": 10}

    # A stolen session alone (no phone) can't make new codes.
    assert (await client.post("/auth/two-step/recovery-codes", json={"code": "000000"}, headers=signed_in)).status_code == 401

    # A minute later, with that minute's code from the phone:
    later = totp.time.time() + 60
    monkeypatch.setattr(totp.time, "time", lambda: later)
    made = await client.post(
        "/auth/two-step/recovery-codes", json={"code": totp.code_at(secret, totp.current_step())}, headers=signed_in
    )
    assert made.status_code == 200, made.text
    new = made.json()["recovery_codes"]

    async def with_recovery(code):
        challenge = (await _password(client, officer))["challenge"]
        return await client.post("/auth/login/recovery-code", json={"challenge": challenge, "code": code}, headers=STAFF)

    assert (await with_recovery(old[0])).status_code == 401  # the old set stopped working
    assert (await with_recovery(new[0])).status_code == 200


@pytest.mark.parametrize("case", ["expired", "other_portal", "forged", "access_token"])
async def test_a_bad_challenge_is_refused(client, make_user, case):
    officer = await make_user("officer")
    now = datetime.now(timezone.utc)
    good = {"sub": str(officer.id), "typ": "mfa_challenge", "portal": "staff", "exp": now + timedelta(minutes=5)}
    challenge = {
        "expired": jwt.encode({**good, "exp": now - timedelta(seconds=1)}, settings.jwt_secret, algorithm="HS256"),
        "other_portal": jwt.encode({**good, "portal": "applicant"}, settings.jwt_secret, algorithm="HS256"),
        "forged": jwt.encode(good, "y" * 40, algorithm="HS256"),
        "access_token": jwt.encode({**good, "typ": "access"}, settings.jwt_secret, algorithm="HS256"),
    }[case]
    response = await client.post("/auth/two-step/set-up", json={"challenge": challenge}, headers=STAFF)
    assert response.status_code == 401
    assert response.json()["detail"] == "Your sign-in took too long or has ended. Please start again."


async def test_a_challenge_through_the_applicant_portal_is_refused(client, make_user):
    officer = await make_user("officer")
    challenge = (await _password(client, officer))["challenge"]
    response = await client.post(
        "/auth/two-step/set-up", json={"challenge": challenge}, headers=portal_headers("applicant")
    )
    assert response.status_code == 401


async def test_without_an_mfa_key_staff_cant_sign_in(client, make_user, monkeypatch):
    monkeypatch.setattr(settings, "mfa_secret_key", None)
    officer = await make_user("officer")
    response = await client.post("/auth/login", json={"email": officer.email, "password": TEST_PASSWORD}, headers=STAFF)
    assert response.status_code == 503
    assert "MFA_SECRET_KEY" in response.json()["detail"]


async def test_sign_in_staff_helper_works(client, make_user):
    token = await sign_in_staff(client, await make_user("officer"))
    assert (await client.get("/auth/me", headers={"Authorization": f"Bearer {token}", **STAFF})).status_code == 200


async def test_the_app_cannot_remove_an_authenticator(db_session):
    with pytest.raises(DBAPIError, match="permission denied"):
        await db_session.execute(text("DELETE FROM core.totp_credentials"))
