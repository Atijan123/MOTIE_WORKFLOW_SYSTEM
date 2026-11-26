"""Sessions kept on the server (step 12f).

A login token used to be all there was: valid until it expired, whatever
happened. Now each sign-in is a row in core.sessions, and the token names
it. On every request (deps.get_current_session):

- the row must exist, belong to the token's user, and not be ended;
- staff: no more than STAFF_IDLE_MINUTES since the last request, and no more
  than STAFF_SESSION_HOURS since signing in;
- applicants: ACCESS_TOKEN_MINUTES after signing in, as before.

`password_checked_at` is when the person last typed their password; moves
marked `needs_recent_password` refuse when that's over REAUTH_MINUTES ago.
"""

import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit.service import record_event
from app.core.config import settings
from app.core.identity.models import LoginSession, User
from app.core.identity.security import create_access_token

# Recording every request would write to the database on every click; once a
# minute is plenty for a 30-minute idle limit.
TOUCH_EVERY = timedelta(seconds=60)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def lifetime(user: User) -> timedelta:
    if user.is_staff:
        return timedelta(hours=settings.staff_session_hours)
    return timedelta(minutes=settings.access_token_minutes)


def idle_limit(user: User) -> timedelta | None:
    return timedelta(minutes=settings.staff_idle_minutes) if user.is_staff else None


async def start(session: AsyncSession, user: User, portal: str | None) -> tuple[str, int]:
    """A new session for someone who has just proved who they are (password,
    and for staff the second step). Returns (token, seconds it lasts)."""
    now = _now()
    row = LoginSession(
        id=secrets.token_urlsafe(24),
        user_id=user.id,
        portal=portal or "none",
        created_at=now,
        last_seen_at=now,
        expires_at=now + lifetime(user),
        password_checked_at=now,  # they typed it to sign in
    )
    session.add(row)
    await session.commit()
    return create_access_token(user.id, row.id, row.expires_at), int(lifetime(user).total_seconds())


class SessionEnded(Exception):
    pass


async def check(session: AsyncSession, row: LoginSession | None, user: User) -> LoginSession:
    """`row` if it's still good for `user`, touched; else SessionEnded (and an idle one is ended)."""
    now = _now()
    if row is None or row.user_id != user.id or row.ended_at is not None or now >= row.expires_at:
        raise SessionEnded()
    idle = idle_limit(user)
    if idle is not None and now - row.last_seen_at > idle:
        row.ended_at, row.ended_reason = now, "idle"
        record_event(session, actor=user, action="auth.signed_out_idle", entity_type="user", entity_id=user.id)
        await session.commit()
        raise SessionEnded()
    if now - row.last_seen_at > TOUCH_EVERY:
        row.last_seen_at = now
        await session.commit()
    return row


async def end(session: AsyncSession, row: LoginSession, user: User) -> None:
    row.ended_at, row.ended_reason = _now(), "signed_out"
    record_event(session, actor=user, action="auth.signed_out", entity_type="user", entity_id=user.id)
    await session.commit()


def password_fresh_until(row: LoginSession) -> datetime:
    return row.password_checked_at + timedelta(minutes=settings.reauth_minutes)


def password_is_fresh(row: LoginSession) -> bool:
    return _now() < password_fresh_until(row)


async def password_checked(session: AsyncSession, row: LoginSession, user: User) -> None:
    row.password_checked_at = _now()
    record_event(session, actor=user, action="auth.password_rechecked", entity_type="user", entity_id=user.id)
    await session.commit()
