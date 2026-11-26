"""Every login attempt, for account lockout and per-IP rate limiting (step 12d).

Revision ID: 0043
Revises: 0042
Create Date: 2026-11-26

core.login_attempts: one row per try at /auth/login (and, from step 12e, per
second-step code). The login counts recent rows to decide whether an
account is locked or an IP is sending too many. The audit log also gets a
row for each attempt; this table exists so the counting is a quick indexed
query rather than a search through JSON.

The app may add and read rows, never change or delete them. Old rows can be
cleared by the owner (an open question: how long to keep them).
"""
import sqlalchemy as sa
from alembic import op

revision = "0043"
down_revision = "0042"
branch_labels = None
depends_on = None

APP_ROLE = "motie_app"


def upgrade() -> None:
    op.create_table(
        "login_attempts",
        sa.Column("id", sa.BigInteger, sa.Identity(), primary_key=True),
        sa.Column("attempted_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        # As typed, trimmed and lower-cased; it need not be anyone's account.
        sa.Column("email", sa.Text, nullable=False),
        sa.Column("client_ip", sa.Text),  # empty when unknown (development: no proxy)
        sa.Column("portal", sa.Text),
        # What happened. Only "bad_password", "wrong_portal" and "bad_code" count
        # towards a lockout; see app/core/identity/login_guard.py.
        sa.Column("outcome", sa.Text, nullable=False),
        sa.Column("user_id", sa.BigInteger, sa.ForeignKey("core.users.id")),
        sa.CheckConstraint("length(email) <= 320", name="login_attempts_email_length"),
        schema="core",
    )
    op.create_index("login_attempts_email_idx", "login_attempts", ["email", "attempted_at"], schema="core")
    op.create_index("login_attempts_ip_idx", "login_attempts", ["client_ip", "attempted_at"], schema="core")
    op.execute(f"GRANT SELECT, INSERT ON core.login_attempts TO {APP_ROLE}")


def downgrade() -> None:
    op.drop_table("login_attempts", schema="core")
