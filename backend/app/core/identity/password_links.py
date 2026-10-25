""""Set your password" links, for accounts made without a password (walk-ins).

issue_link() makes a random token, stores only its SHA-256 hash, and puts
an email with the link in the outbox (core.notifications), in the caller's
transaction. set_password() takes the token back, and if the link is
unused, not revoked and not expired, sets the password and marks the link
used, all at once. A newer link for the same account ends the older ones.

The token goes after "#" in the link (the "fragment"). Browsers never send
the fragment to any server, so it can't end up in a web server's access log
or in a Referer header; the set-password page reads it and posts it here.
"""

import hashlib
import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit.service import record_event
from app.core.config import settings
from app.core.dates import long_date
from app.core.identity.models import PasswordLink, User
from app.core.identity.security import hash_password
from app.core.identity.service import AUDIT_ENTITY, check_password_strength
from app.core.notifications.models import Notification
from app.core.notifications.service import SIGN_OFF

LINK_PATH = "/set-password"


class InvalidLink(Exception):
    """Unknown, used, replaced or expired: one error for all, so a guesser learns nothing."""


def _now() -> datetime:
    # A function, so tests can move the clock (monkeypatch).
    return datetime.now(timezone.utc)


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


async def issue_link(session: AsyncSession, *, user: User, actor: User | None) -> PasswordLink:
    """Email `user` a new link to set their password. Does NOT commit."""
    if user.email is None:
        raise ValueError("An account with no email can't be sent a link.")
    # Only the newest link works: a forwarded or old email is no use.
    await session.execute(
        update(PasswordLink)
        .where(PasswordLink.user_id == user.id, PasswordLink.used_at.is_(None), PasswordLink.revoked_at.is_(None))
        .values(revoked_at=func.now())
    )
    token = secrets.token_urlsafe(32)  # 256 random bits: can't be guessed
    link = PasswordLink(
        user_id=user.id,
        token_sha256=_hash(token),
        created_by=actor.id if actor else None,
        expires_at=_now() + timedelta(hours=settings.password_link_hours),
    )
    session.add(link)
    await session.flush()
    event = record_event(
        session,
        actor=actor,
        action="user.password_link_sent",
        entity_type=AUDIT_ENTITY,
        entity_id=user.id,
        details={"link_id": link.id, "to_email": user.email, "expires_at": link.expires_at.isoformat()},
    )
    await session.flush()  # gives the audit row its id, for the email

    url = f"{settings.public_base_url.rstrip('/')}{LINK_PATH}#token={token}"
    # [CONFIRM] The wording, with the Ministry.
    body = "\n".join(
        [
            f"Dear {user.full_name},",
            "",
            "The Ministry's Records office has opened an application for you. To follow it",
            "online, set a password for your account with this link:",
            "",
            url,
            "",
            f"The link works once, and only until {long_date(link.expires_at.date())}. If it has",
            "expired, ask Records at the Ministry for a new one.",
            "If you haven't been to the Ministry, you can ignore this email.",
            "",
            SIGN_OFF,
        ]
    )
    session.add(
        Notification(
            user_id=user.id,
            to_email=user.email,
            subject="Set your password for the Ministry's online services",
            body=body,
            audit_event_id=event.id,
        )
    )
    return link


async def set_password(session: AsyncSession, *, token: str, password: str) -> User:
    """Use a link: set the account's password, and mark the link used. Commits."""
    # Checked first, so a too-short password doesn't use up the link.
    check_password_strength(password)
    # FOR UPDATE: two clicks at once queue here; the second finds it used.
    link = await session.scalar(
        select(PasswordLink).where(PasswordLink.token_sha256 == _hash(token)).with_for_update()
    )
    user = await session.get(User, link.user_id) if link else None
    if (
        link is None
        or link.used_at is not None
        or link.revoked_at is not None
        or link.expires_at <= _now()
        or user is None
        or not user.is_active
    ):
        raise InvalidLink("This link doesn't work any more. Ask the Ministry for a new one.")
    user.password_hash = hash_password(password)
    link.used_at = func.now()
    record_event(
        session,
        actor=user,
        action="user.password_set",
        entity_type=AUDIT_ENTITY,
        entity_id=user.id,
        details={"link_id": link.id},
    )
    await session.commit()
    return user
