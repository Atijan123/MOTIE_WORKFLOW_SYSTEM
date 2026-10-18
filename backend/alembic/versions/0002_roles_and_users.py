"""Roles, users and the link between them.

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-18
"""
import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

# [CONFIRM] Placeholder role list, based on the chain of command in CLAUDE.md.
# Check the real list and names with the Ministry.
INITIAL_ROLES = [
    {"code": "applicant", "name": "Applicant"},
    {"code": "records_officer", "name": "Records Officer"},
    {"code": "minister", "name": "Minister"},
    {"code": "permanent_secretary", "name": "Permanent Secretary"},
    {"code": "director", "name": "Director"},
    {"code": "officer", "name": "Subject Officer"},
    {"code": "admin", "name": "System Administrator"},
]


def upgrade() -> None:
    # roles: the kinds of job a user can do. `code` is what the program checks
    # (never changes); `name` is what people see (can be renamed).
    op.create_table(
        "roles",
        sa.Column("id", sa.SmallInteger, sa.Identity(), primary_key=True),
        sa.Column("code", sa.Text, nullable=False, unique=True),
        sa.Column("name", sa.Text, nullable=False),
        schema="core",
    )

    # users: one row per person who can log in. We store a hash of the password,
    # never the password. Users are deactivated (is_active = false), not deleted,
    # so the audit log can always say who did what.
    op.create_table(
        "users",
        sa.Column("id", sa.BigInteger, sa.Identity(), primary_key=True),
        sa.Column("email", sa.Text, nullable=False, unique=True),
        sa.Column("full_name", sa.Text, nullable=False),
        sa.Column("password_hash", sa.Text, nullable=False),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        # Emails are stored lowercase so "A@x.gm" and "a@x.gm" can't be two accounts.
        sa.CheckConstraint("email = lower(email)", name="users_email_lowercase"),
        schema="core",
    )

    # user_roles: which user has which role. The two-column primary key stops
    # the same role being given to the same user twice.
    op.create_table(
        "user_roles",
        sa.Column(
            "user_id",
            sa.BigInteger,
            sa.ForeignKey("core.users.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("role_id", sa.SmallInteger, sa.ForeignKey("core.roles.id"), primary_key=True),
        schema="core",
    )

    roles = sa.table("roles", sa.column("code"), sa.column("name"), schema="core")
    op.bulk_insert(roles, INITIAL_ROLES)


def downgrade() -> None:
    op.drop_table("user_roles", schema="core")
    op.drop_table("users", schema="core")
    op.drop_table("roles", schema="core")
