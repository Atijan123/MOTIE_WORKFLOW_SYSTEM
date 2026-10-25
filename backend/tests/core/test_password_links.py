""""Set your password" links (core/identity/password_links.py): single use,
expiring, stored as a hash, sent through the outbox."""

import hashlib
import re
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError

from app.core.audit.models import AuditEvent
from app.core.identity import password_links
from app.core.identity.models import PasswordLink, User
from app.core.notifications.models import Notification
from app.core.notifications.sender import FakeSender
from app.core.notifications.worker import send_pending
from tests.support import facility_letter_form

pytestmark = pytest.mark.anyio

class BrokenSender:
    async def send(self, email):
        raise ConnectionError("mail server unreachable")


NEW_PASSWORD = "a long new password 42"


async def _walk_in(act, people, email="setme@example.gm") -> None:
    body = {"applicant_email": email, "applicant_name": "Isatou Bah", "form": facility_letter_form()}
    response = await act(people["records_officer"], "post", "/etls/facility-letters/walk-in", json=body)
    assert response.status_code == 201, response.text


async def _tokens(db_session, email="setme@example.gm") -> list[str]:
    """The tokens in the emails sent to this address, oldest first."""
    emails = await db_session.scalars(
        select(Notification).where(Notification.to_email == email).order_by(Notification.id)
    )
    return [re.search(r"#token=(\S+)", e.body).group(1) for e in emails]


async def _set(client, token, password=NEW_PASSWORD):
    return await client.post("/auth/set-password", json={"token": token, "password": password})


async def _login(client, email="setme@example.gm", password=NEW_PASSWORD):
    return await client.post("/auth/login", json={"email": email, "password": password})


async def test_the_link_sets_the_password_and_then_they_can_log_in(act, people, client, db_session):
    await _walk_in(act, people)
    [token] = await _tokens(db_session)
    response = await _set(client, token)
    assert response.status_code == 204, response.text
    assert (await _login(client)).status_code == 200

    user = await db_session.scalar(select(User).where(User.email == "setme@example.gm"))
    actions = list(
        await db_session.scalars(
            select(AuditEvent.action).where(AuditEvent.entity_type == "user", AuditEvent.entity_id == str(user.id))
        )
    )
    assert actions == ["user.created_for_walk_in", "user.password_link_sent", "user.password_set"]


async def test_a_link_works_once(act, people, client, db_session):
    await _walk_in(act, people)
    [token] = await _tokens(db_session)
    assert (await _set(client, token)).status_code == 204
    again = await _set(client, token, "someone else's password 1")
    assert again.status_code == 400
    assert (await _login(client)).status_code == 200  # the first password stands


async def test_an_expired_link_is_refused(act, people, client, db_session, monkeypatch):
    await _walk_in(act, people)
    [token] = await _tokens(db_session)
    later = password_links._now() + timedelta(hours=73)
    monkeypatch.setattr(password_links, "_now", lambda: later)
    response = await _set(client, token)
    assert response.status_code == 400
    assert "Ask the Ministry for a new one" in response.json()["detail"]


async def test_a_newer_link_ends_the_older_one(act, people, client, db_session):
    await _walk_in(act, people)
    await _walk_in(act, people)  # back again before setting a password: a fresh link
    old, new = await _tokens(db_session)
    assert (await _set(client, old)).status_code == 400
    assert (await _set(client, new)).status_code == 204


async def test_unknown_and_used_links_look_the_same(act, people, client, db_session):
    await _walk_in(act, people)
    [token] = await _tokens(db_session)
    await _set(client, token)
    used = await _set(client, token)
    unknown = await _set(client, "not-a-real-token")
    assert used.status_code == unknown.status_code == 400
    assert used.json() == unknown.json()


async def test_a_short_password_is_refused_and_the_link_still_works(act, people, client, db_session):
    await _walk_in(act, people)
    [token] = await _tokens(db_session)
    assert (await _set(client, token, "short")).status_code == 422
    assert (await _set(client, token)).status_code == 204


async def test_only_a_hash_of_the_token_is_stored(act, people, db_session):
    await _walk_in(act, people)
    [token] = await _tokens(db_session)
    user = await db_session.scalar(select(User).where(User.email == "setme@example.gm"))
    [link] = list(await db_session.scalars(select(PasswordLink).where(PasswordLink.user_id == user.id)))
    assert link.token_sha256 == hashlib.sha256(token.encode()).hexdigest()
    # The audit row says a link went, and where, but not what it was.
    sent = await db_session.scalar(select(AuditEvent).where(AuditEvent.action == "user.password_link_sent"))
    assert token not in str(sent.details)


async def test_a_deactivated_account_cannot_use_its_link(act, people, client, db_session):
    await _walk_in(act, people)
    [token] = await _tokens(db_session)
    user = await db_session.scalar(select(User).where(User.email == "setme@example.gm"))
    user.is_active = False
    await db_session.commit()
    assert (await _set(client, token)).status_code == 400


# --- The outbox copy loses the link once it's no use (0038) -----------------


async def _link_email(db_session, email="setme@example.gm") -> Notification:
    return await db_session.scalar(select(Notification).where(Notification.to_email == email))


async def test_a_sent_email_no_longer_holds_the_token(act, people, db_session):
    await _walk_in(act, people)
    [token] = await _tokens(db_session)
    sender = FakeSender()
    await send_pending(db_session, sender, limit=1000)

    # The applicant got the working link...
    [sent] = [e for e in sender.sent if e.to == "setme@example.gm"]
    assert f"#token={token}" in sent.body
    # ...but the stored copy no longer has it.
    stored = await _link_email(db_session)
    await db_session.refresh(stored)
    assert stored.sent_at is not None
    assert token not in stored.body and "#token=" not in stored.body
    assert "[link removed after sending]" in stored.body
    assert "Dear Isatou Bah" in stored.body  # the rest is kept


async def test_a_failed_email_keeps_its_link_for_the_retry(act, people, db_session):
    await _walk_in(act, people)
    [token] = await _tokens(db_session)
    await send_pending(db_session, BrokenSender(), limit=1000)
    stored = await _link_email(db_session)
    await db_session.refresh(stored)
    assert stored.sent_at is None and stored.attempts == 1
    assert f"#token={token}" in stored.body


async def test_an_expired_link_is_scrubbed_and_not_sent(people, db_session):
    applicant = people["applicant"]
    # A link that expired an hour ago, its email never sent (e.g. the mail server was down).
    link = PasswordLink(
        user_id=applicant.id,
        token_sha256=hashlib.sha256(b"old-token").hexdigest(),
        created_at=datetime.now(timezone.utc) - timedelta(hours=73),
        expires_at=datetime.now(timezone.utc) - timedelta(hours=1),
    )
    db_session.add(link)
    await db_session.flush()
    email = Notification(
        user_id=applicant.id,
        to_email=applicant.email,
        subject="Set your password",
        body="Use this: http://localhost:3000/set-password#token=old-token\nThanks",
        password_link_id=link.id,
    )
    db_session.add(email)
    await db_session.commit()

    sender = FakeSender()
    await send_pending(db_session, sender, limit=1000)
    await db_session.refresh(email)
    assert email.body == "Use this: [link removed after it expired]\nThanks"
    assert email.sent_at is None
    assert not [e for e in sender.sent if e.to == applicant.email]


async def test_the_app_still_cannot_rewrite_an_email(people, db_session):
    with pytest.raises(DBAPIError):
        await db_session.execute(text("UPDATE core.notifications SET body = 'something else'"))
