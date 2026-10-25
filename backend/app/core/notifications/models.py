"""The notifications outbox. Created by alembic/versions/0033_notifications.py."""

from datetime import datetime

from sqlalchemy import BigInteger, CheckConstraint, DateTime, ForeignKey, Identity, Index, SmallInteger, Text, func, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Notification(Base):
    """One email to send. Written in the same transaction as what it tells of
    (service.py); sent and marked by the worker (worker.py). The body is what
    was sent, except that a password link is replaced once it's sent or
    expired (0038)."""

    __tablename__ = "notifications"
    __table_args__ = (
        CheckConstraint("attempts >= 0", name="notifications_attempts_positive"),
        Index("notifications_pending_idx", "next_attempt_at", postgresql_where=text("sent_at IS NULL")),
        Index("notifications_case_idx", "case_id"),
        {"schema": "core"},
    )
    __mapper_args__ = {"eager_defaults": True}

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("core.users.id"))
    to_email: Mapped[str] = mapped_column(Text)  # as it was when written
    subject: Mapped[str] = mapped_column(Text)
    body: Mapped[str] = mapped_column(Text)
    case_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("core.cases.id"))
    audit_event_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("core.audit_log.id"))
    # The "set your password" link in the body, if any (0038). A trigger takes
    # it out of the body when the email is marked sent.
    password_link_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("core.password_links.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    next_attempt_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    attempts: Mapped[int] = mapped_column(SmallInteger, server_default="0")
    last_error: Mapped[str | None] = mapped_column(Text)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
