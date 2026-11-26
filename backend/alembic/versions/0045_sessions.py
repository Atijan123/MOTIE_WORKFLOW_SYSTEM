"""Sessions on the server, and moves that need a recent password (step 12f).

Revision ID: 0045
Revises: 0044
Create Date: 2026-11-26

core.sessions: one row per sign-in. The login token names its row (`sid`),
and every request checks it (identity/sessions.py), so:
- staff are signed out after STAFF_IDLE_MINUTES without a request
  (`last_seen_at`) and STAFF_SESSION_HOURS after signing in (`expires_at`);
- signing out really ends the session (`ended_at`), instead of only
  deleting the browser's cookie while the token keeps working;
- `password_checked_at` says when this person last typed their password, for
  moves that need it recently.

core.workflow_transitions.needs_recent_password: the move asks for the
password again if it was last checked more than REAUTH_MINUTES ago. Set for
signing a facility letter and approving an ETLS application. It's data, like
the other rules on a move, so another module's important moves can use it.
"""
import sqlalchemy as sa
from alembic import op

revision = "0045"
down_revision = "0044"
branch_labels = None
depends_on = None

APP_ROLE = "motie_app"

# (workflow, the status the move goes to)
GUARDED = [("etls_facility_letter", "signed"), ("etls_application", "approved")]


def upgrade() -> None:
    op.create_table(
        "sessions",
        # Random, unguessable; the token carries it. Not a secret on its own:
        # a token must also be signed with JWT_SECRET.
        sa.Column("id", sa.Text, primary_key=True),
        sa.Column("user_id", sa.BigInteger, sa.ForeignKey("core.users.id"), nullable=False),
        sa.Column("portal", sa.Text, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("password_checked_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True)),
        sa.Column("ended_reason", sa.Text),  # signed_out, idle
        sa.CheckConstraint("expires_at > created_at", name="sessions_expire_later"),
        schema="core",
    )
    op.create_index("sessions_user_idx", "sessions", ["user_id"], schema="core")
    op.execute(f"GRANT SELECT, INSERT ON core.sessions TO {APP_ROLE}")
    op.execute(
        f"GRANT UPDATE (last_seen_at, password_checked_at, ended_at, ended_reason) ON core.sessions TO {APP_ROLE}"
    )

    op.add_column(
        "workflow_transitions",
        sa.Column("needs_recent_password", sa.Boolean, nullable=False, server_default=sa.false()),
        schema="core",
    )
    for workflow, to_status in GUARDED:
        op.execute(
            sa.text(
                """
                UPDATE core.workflow_transitions x SET needs_recent_password = true
                FROM core.workflows w, core.workflow_statuses t
                WHERE x.workflow_id = w.id AND w.code = :workflow
                  AND t.id = x.to_status_id AND t.code = :to_status
                """
            ).bindparams(workflow=workflow, to_status=to_status)
        )


def downgrade() -> None:
    op.drop_column("workflow_transitions", "needs_recent_password", schema="core")
    op.drop_table("sessions", schema="core")
