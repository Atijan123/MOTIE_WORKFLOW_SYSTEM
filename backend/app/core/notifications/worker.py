"""Sends the emails waiting in the outbox (core.notifications).

    docker compose run --rm tools python -m app.core.notifications.worker --once
    docker compose up notifier        (runs it every NOTIFICATION_POLL_SECONDS)

Each email is sent with its row locked (FOR UPDATE SKIP LOCKED), then marked
sent and committed before the next. So two workers never send the same email,
and a crash costs at most one repeat. A failed send is tried again later,
waiting twice as long each time, and given up after MAX_ATTEMPTS (it stays in
the table with its last error, for the administrator).
"""

import argparse
import asyncio
import logging
from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

import app.models  # noqa: F401  (every table: the outbox's foreign keys point at audit_log, cases, users)
from app.core.config import settings
from app.core.notifications.models import Notification
from app.core.notifications.sender import Email, Sender, get_sender

logger = logging.getLogger(__name__)

MAX_ATTEMPTS = 8  # the last wait is 2**7 = 128 minutes; about 4 hours in all


async def send_pending(session: AsyncSession, sender: Sender, *, limit: int = 50) -> int:
    """Send up to `limit` due emails, one at a time. Returns how many were sent."""
    sent = 0
    for _ in range(limit):
        notification = await session.scalar(
            select(Notification)
            .where(
                Notification.sent_at.is_(None),
                Notification.next_attempt_at <= func.now(),
                Notification.attempts < MAX_ATTEMPTS,
            )
            .order_by(Notification.id)
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        if notification is None:
            break
        notification.attempts += 1
        try:
            await sender.send(Email(notification.to_email, notification.subject, notification.body))
        except Exception as exc:  # any failure: try again later
            notification.last_error = f"{type(exc).__name__}: {exc}"[:500]
            notification.next_attempt_at = func.now() + timedelta(minutes=2 ** (notification.attempts - 1))
            logger.warning("Email %s failed (attempt %s): %s", notification.id, notification.attempts, exc)
        else:
            notification.sent_at = func.now()
            notification.last_error = None
            sent += 1
        await session.commit()
    return sent


async def _run(once: bool) -> None:
    # Imported here so `--help` works without a database.
    from app.db.session import SessionLocal, engine

    sender = get_sender()
    try:
        while True:
            async with SessionLocal() as session:
                count = await send_pending(session, sender)
            if count:
                logger.info("Sent %s email(s)", count)
            if once:
                break
            await asyncio.sleep(settings.notification_poll_seconds)
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description="Send the emails waiting in the outbox.")
    parser.add_argument("--once", action="store_true", help="send what's due, then stop")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    asyncio.run(_run(args.once))


if __name__ == "__main__":
    main()
