"""Login protection (step 12d): lockout, per-IP rate limiting, and a record of
every attempt in core.login_attempts and the audit log.

The rules:
- An account is locked after LOCKOUT_FAILURES failed tries within
  LOCKOUT_MINUTES. Failures before its last successful login don't count.
  It unlocks by itself once the window has passed.
- One IP address may try at most LOGIN_IP_LIMIT times per
  LOGIN_IP_WINDOW_MINUTES, successes included, across all accounts.
- Tries refused *because of* a lock or a limit are recorded but don't count,
  so knocking on a locked door doesn't keep it locked for ever.

Lockout is counted by the email typed, whether or not it is anyone's
account. So "locked" says nothing about whether an account exists.
"""

from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit.service import record_event
from app.core.config import settings
from app.core.identity.channel import Channel
from app.core.identity.models import LoginAttempt, User

# Outcomes that count towards a lockout. "wrong_portal" counts too: a staff
# password typed into the applicant portal gets the wrong-password answer, and
# if it didn't count, five tries without a lock would reveal it was right.
FAILURES = ("bad_password", "wrong_portal", "bad_code")
SUCCESS = "success"


class LoginRefused(Exception):
    """Locked or rate limited. `message` is safe to show; `minutes` until it may be tried again."""

    def __init__(self, message: str, minutes: int):
        super().__init__(message)
        self.message = message
        self.minutes = minutes


def _clean_email(email: str) -> str:
    return email.strip().lower()[:320]


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _minutes_until(moment: datetime) -> int:
    return max(1, -(-int((moment - _now()).total_seconds()) // 60))  # round up


async def check(session: AsyncSession, email: str, channel: Channel) -> None:
    """Raise LoginRefused if this IP is over its limit or this account is locked."""
    if channel.client_ip:
        # Without a known IP (development: no proxy) there is nothing to count
        # per IP; behind Caddy the IP is always known.
        window = timedelta(minutes=settings.login_ip_window_minutes)
        times = (
            await session.scalars(
                select(LoginAttempt.attempted_at)
                .where(LoginAttempt.client_ip == channel.client_ip, LoginAttempt.attempted_at > _now() - window)
                .order_by(LoginAttempt.attempted_at.desc())
                .limit(settings.login_ip_limit)
            )
        ).all()
        if len(times) >= settings.login_ip_limit:
            raise LoginRefused(
                "Too many sign-in attempts from this network. Try again in a few minutes.",
                _minutes_until(times[-1] + window),
            )

    window = timedelta(minutes=settings.lockout_minutes)
    email = _clean_email(email)
    last_success = await session.scalar(
        select(func.max(LoginAttempt.attempted_at)).where(LoginAttempt.email == email, LoginAttempt.outcome == SUCCESS)
    )
    since = max(_now() - window, last_success) if last_success else _now() - window
    failures = (
        await session.scalars(
            select(LoginAttempt.attempted_at)
            .where(LoginAttempt.email == email, LoginAttempt.outcome.in_(FAILURES), LoginAttempt.attempted_at > since)
            .order_by(LoginAttempt.attempted_at.desc())
            .limit(settings.lockout_failures)
        )
    ).all()
    if len(failures) >= settings.lockout_failures:
        # Unlocks when the oldest of the failures that locked it leaves the window.
        minutes = _minutes_until(failures[-1] + window)
        raise LoginRefused(
            f"Too many failed attempts: this account is locked. Try again in {minutes} minute{'s' * (minutes != 1)}.",
            minutes,
        )


async def record(
    session: AsyncSession, *, email: str, channel: Channel, outcome: str, user: User | None = None
) -> None:
    """Write the attempt and its audit row, and commit (a refused login raises
    straight after, so nothing else would commit them)."""
    email = _clean_email(email)
    session.add(
        LoginAttempt(email=email, client_ip=channel.client_ip, portal=channel.portal, outcome=outcome, user_id=user.id if user else None)
    )
    record_event(
        session,
        actor=user if outcome == SUCCESS else None,
        action="auth.login_succeeded" if outcome == SUCCESS else "auth.login_failed",
        # An unknown email has no user row: the audit row is then about the email typed.
        entity_type="user" if user else "login",
        entity_id=user.id if user else email,
        details={"outcome": outcome, "portal": channel.portal, "ip": channel.client_ip},
    )
    await session.commit()
