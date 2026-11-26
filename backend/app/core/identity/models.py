from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    SmallInteger,
    Table,
    Text,
    func,
    true,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

# These classes describe tables created by alembic/versions/0002_roles_and_users.py
# (roles, users) and 0008_positions.py (departments, positions, holders).
# If you change one, write a migration too; tests/test_migrations.py fails if they drift apart.

user_roles = Table(
    "user_roles",
    Base.metadata,
    Column("user_id", BigInteger, ForeignKey("core.users.id", ondelete="CASCADE"), primary_key=True),
    Column("role_id", SmallInteger, ForeignKey("core.roles.id"), primary_key=True),
    schema="core",
)

position_holders = Table(
    "position_holders",
    Base.metadata,
    Column("position_id", SmallInteger, ForeignKey("core.positions.id"), primary_key=True),
    Column("user_id", BigInteger, ForeignKey("core.users.id"), primary_key=True),
    Column("assigned_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Index("position_holders_user_idx", "user_id"),
    schema="core",
)


class Role(Base):
    __tablename__ = "roles"
    __table_args__ = {"schema": "core"}

    id: Mapped[int] = mapped_column(SmallInteger, Identity(), primary_key=True)
    code: Mapped[str] = mapped_column(Text, unique=True)
    name: Mapped[str] = mapped_column(Text)


class Department(Base):
    __tablename__ = "departments"
    __table_args__ = {"schema": "core"}

    id: Mapped[int] = mapped_column(SmallInteger, Identity(), primary_key=True)
    code: Mapped[str] = mapped_column(Text, unique=True)
    name: Mapped[str] = mapped_column(Text)


class Position(Base):
    """A post in the Ministry ("Director of Trade"), held by zero or more users.

    Workflow approvals attach to positions, not to people, so a change of
    Director is one row in position_holders, not a change to any workflow.
    """

    __tablename__ = "positions"
    __table_args__ = (
        CheckConstraint("reports_to_id <> id", name="positions_not_own_boss"),
        {"schema": "core"},
    )

    id: Mapped[int] = mapped_column(SmallInteger, Identity(), primary_key=True)
    code: Mapped[str] = mapped_column(Text, unique=True)
    title: Mapped[str] = mapped_column(Text)
    department_id: Mapped[int] = mapped_column(SmallInteger, ForeignKey("core.departments.id"))
    # The post above this one; empty only at the top. No relationship objects on
    # purpose: positions are loaded with every user, on every request, and
    # following the chain of bosses each time would cost a query per level.
    reports_to_id: Mapped[int | None] = mapped_column(SmallInteger, ForeignKey("core.positions.id"))


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint("email = lower(email)", name="users_email_lowercase"),
        {"schema": "core"},
    )
    # Read database-filled columns (id, is_active, created_at) back right after INSERT.
    __mapper_args__ = {"eager_defaults": True}

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    # Empty only for a walk-in applicant who gave no email (0035): they can't
    # log in or be emailed, and Records tells them of each step.
    email: Mapped[str | None] = mapped_column(Text, unique=True)
    full_name: Mapped[str] = mapped_column(Text)
    # Empty until the person sets a password (a walk-in applicant, from the
    # emailed link). Nobody can log in to an account without one.
    password_hash: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=true())
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # lazy="selectin": load roles together with the user. In async code a role
    # list can't be loaded later "on first touch", so we fetch it up front.
    roles: Mapped[list[Role]] = relationship(secondary=user_roles, lazy="selectin")
    # Change through identity/service.py assign_position(), which writes the audit row.
    positions: Mapped[list[Position]] = relationship(
        secondary=position_holders, lazy="selectin", viewonly=True
    )

    @property
    def role_codes(self) -> set[str]:
        return {role.code for role in self.roles}

    @property
    def is_staff(self) -> bool:
        """Any role besides "applicant" makes this a staff account, as the
        frontend's isStaff() says. Staff accounts work only through the staff app."""
        return bool(self.role_codes - {"applicant"})

    @property
    def portal(self) -> str:
        return "staff" if self.is_staff else "applicant"

    @property
    def position_codes(self) -> set[str]:
        return {position.code for position in self.positions}


class PasswordLink(Base):
    """A "set your password" link (0035). Only the token's hash is stored, so
    reading this table doesn't let anyone use a link. Created and used through
    identity/password_links.py."""

    __tablename__ = "password_links"
    __table_args__ = (
        CheckConstraint("expires_at > created_at", name="password_links_expire_later"),
        CheckConstraint("used_at IS NULL OR revoked_at IS NULL", name="password_links_used_or_revoked"),
        Index("password_links_user_idx", "user_id"),
        {"schema": "core"},
    )
    __mapper_args__ = {"eager_defaults": True}

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("core.users.id"))
    token_sha256: Mapped[str] = mapped_column(Text, unique=True)
    created_by: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("core.users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class LoginAttempt(Base):
    """One try at logging in (0043), for lockout and rate limiting. Written and
    counted by identity/login_guard.py; the app may never change or delete one."""

    __tablename__ = "login_attempts"
    __table_args__ = (
        CheckConstraint("length(email) <= 320", name="login_attempts_email_length"),
        Index("login_attempts_email_idx", "email", "attempted_at"),
        Index("login_attempts_ip_idx", "client_ip", "attempted_at"),
        {"schema": "core"},
    )
    __mapper_args__ = {"eager_defaults": True}

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    attempted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    email: Mapped[str] = mapped_column(Text)
    client_ip: Mapped[str | None] = mapped_column(Text)
    portal: Mapped[str | None] = mapped_column(Text)
    outcome: Mapped[str] = mapped_column(Text)
    user_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("core.users.id"))


class TotpCredential(Base):
    """A staff member's authenticator app (0044). Read and changed through identity/two_step.py."""

    __tablename__ = "totp_credentials"
    __table_args__ = {"schema": "core"}
    __mapper_args__ = {"eager_defaults": True}

    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("core.users.id"), primary_key=True)
    secret_encrypted: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_used_step: Mapped[int | None] = mapped_column(BigInteger)


class RecoveryCode(Base):
    """One one-time recovery code (0044); only its hash is stored."""

    __tablename__ = "recovery_codes"
    __table_args__ = (
        CheckConstraint("used_at IS NULL OR revoked_at IS NULL", name="recovery_codes_used_or_revoked"),
        Index("recovery_codes_user_idx", "user_id"),
        {"schema": "core"},
    )
    __mapper_args__ = {"eager_defaults": True}

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("core.users.id"))
    code_sha256: Mapped[str] = mapped_column(Text, unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class LoginSession(Base):
    """One sign-in (0045). The token names it; identity/sessions.py checks it on every request."""

    __tablename__ = "sessions"
    __table_args__ = (
        CheckConstraint("expires_at > created_at", name="sessions_expire_later"),
        Index("sessions_user_idx", "user_id"),
        {"schema": "core"},
    )

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("core.users.id"))
    portal: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    password_checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ended_reason: Mapped[str | None] = mapped_column(Text)
