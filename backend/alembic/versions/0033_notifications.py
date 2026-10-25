"""Notifications: an outbox of emails to applicants, sent by a background worker.

Revision ID: 0033
Revises: 0032
Create Date: 2026-10-25

SCREENS.md global rules: applicants are emailed at each status change and
when a case is returned.

The move writes a row here in its own transaction (the "outbox"), so an
email exists exactly when the status change does: never an email about a
move that rolled back, never a move whose email was forgotten. A separate
worker (backend/app/core/notifications/worker.py) sends pending rows and
marks them sent; a failure is retried later with a growing wait.

The app may add rows and record sending (sent_at, attempts, last_error,
next_attempt_at); it may never change who an email goes to or what it says.
"""
import sqlalchemy as sa
from alembic import op

revision = "0033"
down_revision = "0032"
branch_labels = None
depends_on = None

APP_ROLE = "motie_app"


def upgrade() -> None:
    op.create_table(
        "notifications",
        sa.Column("id", sa.BigInteger, sa.Identity(), primary_key=True),
        sa.Column("user_id", sa.BigInteger, sa.ForeignKey("core.users.id"), nullable=False),
        # Copied at the time, so the record shows where it actually went.
        sa.Column("to_email", sa.Text, nullable=False),
        sa.Column("subject", sa.Text, nullable=False),
        sa.Column("body", sa.Text, nullable=False),
        sa.Column("case_id", sa.BigInteger, sa.ForeignKey("core.cases.id")),
        # The move it tells of: its audit row.
        sa.Column("audit_event_id", sa.BigInteger, sa.ForeignKey("core.audit_log.id")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("attempts", sa.SmallInteger, nullable=False, server_default="0"),
        sa.Column("last_error", sa.Text),
        sa.Column("sent_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint("attempts >= 0", name="notifications_attempts_positive"),
        schema="core",
    )
    # The worker's question: what is due and not yet sent?
    op.create_index(
        "notifications_pending_idx",
        "notifications",
        ["next_attempt_at"],
        schema="core",
        postgresql_where=sa.text("sent_at IS NULL"),
    )
    op.create_index("notifications_case_idx", "notifications", ["case_id"], schema="core")
    op.execute(f"GRANT SELECT, INSERT ON core.notifications TO {APP_ROLE}")
    op.execute(
        f"GRANT UPDATE (sent_at, attempts, last_error, next_attempt_at) ON core.notifications TO {APP_ROLE}"
    )


def downgrade() -> None:
    op.drop_table("notifications", schema="core")
