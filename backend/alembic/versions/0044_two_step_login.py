"""Two-step login for staff: authenticator secrets and recovery codes (step 12e).

Revision ID: 0044
Revises: 0043
Create Date: 2026-11-26

core.totp_credentials: one per staff member. `secret_encrypted` is their
authenticator secret, encrypted with MFA_SECRET_KEY (identity/two_step.py),
so a copy of the database alone can't make their codes. `confirmed_at` is
empty while they are still setting it up. `last_used_step` is the 30-second
step of the last code used: a code can't be used twice.

core.recovery_codes: ten one-time codes per staff member, for a lost phone.
Only their SHA-256 hashes are stored (the codes are long and random, so a
fast hash is enough; passwords need Argon2 because people choose them).

The app may add rows and mark them used, never delete them. Removing a lost
authenticator is done by an admin from the command line (identity/cli.py,
reset-two-step), as the schema owner.
"""
import sqlalchemy as sa
from alembic import op

revision = "0044"
down_revision = "0043"
branch_labels = None
depends_on = None

APP_ROLE = "motie_app"


def upgrade() -> None:
    op.create_table(
        "totp_credentials",
        sa.Column("user_id", sa.BigInteger, sa.ForeignKey("core.users.id"), primary_key=True),
        sa.Column("secret_encrypted", sa.Text, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("confirmed_at", sa.DateTime(timezone=True)),
        sa.Column("last_used_step", sa.BigInteger),
        schema="core",
    )
    op.execute(f"GRANT SELECT, INSERT ON core.totp_credentials TO {APP_ROLE}")
    # The secret may be replaced only while setting up (two_step.start_enrolment()).
    op.execute(
        f"GRANT UPDATE (secret_encrypted, created_at, confirmed_at, last_used_step) ON core.totp_credentials TO {APP_ROLE}"
    )

    op.create_table(
        "recovery_codes",
        sa.Column("id", sa.BigInteger, sa.Identity(), primary_key=True),
        sa.Column("user_id", sa.BigInteger, sa.ForeignKey("core.users.id"), nullable=False),
        sa.Column("code_sha256", sa.Text, nullable=False, unique=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("used_at", sa.DateTime(timezone=True)),
        # Set on every unused code when a new set is made.
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint("used_at IS NULL OR revoked_at IS NULL", name="recovery_codes_used_or_revoked"),
        schema="core",
    )
    op.create_index("recovery_codes_user_idx", "recovery_codes", ["user_id"], schema="core")
    op.execute(f"GRANT SELECT, INSERT ON core.recovery_codes TO {APP_ROLE}")
    op.execute(f"GRANT UPDATE (used_at, revoked_at) ON core.recovery_codes TO {APP_ROLE}")


def downgrade() -> None:
    op.drop_table("recovery_codes", schema="core")
    op.drop_table("totp_credentials", schema="core")
