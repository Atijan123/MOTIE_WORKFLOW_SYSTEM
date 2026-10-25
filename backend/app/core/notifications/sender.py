"""How an email actually leaves: one interface, so the mail server can change.

Only a fake sender exists yet. It logs each email and keeps it in memory,
which is all development and tests need. [CONFIRM] the Ministry's mail
server (SMTP host, port, login, sender address); then an SmtpSender that
uses Python's built-in smtplib joins it here, chosen by EMAIL_BACKEND.
"""

import logging
from dataclasses import dataclass
from typing import Protocol

from app.core.config import settings

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Email:
    to: str
    subject: str
    body: str


class Sender(Protocol):
    async def send(self, email: Email) -> None:
        """Send it, or raise. The worker retries on any exception."""


class FakeSender:
    """Sends nothing: logs the email and remembers it (tests read `sent`)."""

    def __init__(self) -> None:
        self.sent: list[Email] = []

    async def send(self, email: Email) -> None:
        self.sent.append(email)
        logger.info("Email (not sent, fake sender) to %s: %s", email.to, email.subject)


def get_sender() -> Sender:
    if settings.email_backend == "fake":
        return FakeSender()
    raise ValueError(f"Unknown EMAIL_BACKEND {settings.email_backend!r}")
