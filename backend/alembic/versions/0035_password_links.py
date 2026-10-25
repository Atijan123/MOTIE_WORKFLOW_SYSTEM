"""Walk-in accounts: no password until the applicant sets one from an emailed link.

Revision ID: 0035
Revises: 0034
Create Date: 2026-10-25

Before, Records' walk-in made an account with a random password nobody knew,
so the applicant could never log in. Now:
- core.users.password_hash may be empty: an account nobody can log in to
  (yet). Login refuses it. Accounts made for walk-ins before now are emptied
  too: nobody ever knew their random password, so nothing is lost.
- core.users.email may be empty: a walk-in applicant with no email. The
  account can't log in or be emailed; Records tells them of each step.
- core.password_links: "set your password" links. Only a hash of each
  link's token is stored, so someone who reads this table can't use a link.
  A link works once (used_at), expires (expires_at), and a newer link for the
  same account ends the older ones (revoked_at).
"""
import sqlalchemy as sa
from alembic import op

revision = "0035"
down_revision = "0034"
branch_labels = None
depends_on = None

APP_ROLE = "motie_app"


def upgrade() -> None:
    op.alter_column("users", "password_hash", nullable=True, schema="core")
    op.alter_column("users", "email", nullable=True, schema="core")
    op.execute(
        """
        UPDATE core.users SET password_hash = NULL
        WHERE id IN (
            SELECT entity_id::bigint FROM core.audit_log
            WHERE action = 'user.created_for_walk_in' AND entity_type = 'user'
        )
        """
    )
    op.create_table(
        "password_links",
        sa.Column("id", sa.BigInteger, sa.Identity(), primary_key=True),
        sa.Column("user_id", sa.BigInteger, sa.ForeignKey("core.users.id"), nullable=False),
        # SHA-256 of the token in the link, as hex. The token itself is never stored here.
        sa.Column("token_sha256", sa.Text, nullable=False, unique=True),
        sa.Column("created_by", sa.BigInteger, sa.ForeignKey("core.users.id")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True)),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint("expires_at > created_at", name="password_links_expire_later"),
        sa.CheckConstraint("used_at IS NULL OR revoked_at IS NULL", name="password_links_used_or_revoked"),
        schema="core",
    )
    op.create_index("password_links_user_idx", "password_links", ["user_id"], schema="core")
    op.execute(f"GRANT SELECT, INSERT ON core.password_links TO {APP_ROLE}")
    op.execute(f"GRANT UPDATE (used_at, revoked_at) ON core.password_links TO {APP_ROLE}")


def downgrade() -> None:
    conn = op.get_bind()
    unusable = conn.execute(
        sa.text("SELECT count(*) FROM core.users WHERE password_hash IS NULL OR email IS NULL")
    ).scalar()
    if unusable:
        # They'd need an invented email or password; refuse instead.
        raise RuntimeError("Can't downgrade 0035: some accounts have no email or no password.")
    op.drop_table("password_links", schema="core")
    op.alter_column("users", "email", nullable=False, schema="core")
    op.alter_column("users", "password_hash", nullable=False, schema="core")
