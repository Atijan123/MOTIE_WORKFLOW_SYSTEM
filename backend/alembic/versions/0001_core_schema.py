"""Create the core schema.

Revision ID: 0001
Revises:
Create Date: 2026-10-18
"""
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # A schema is a named folder for tables inside one database. Shared tables
    # (users, workflow, audit) live in "core"; each module later gets its own
    # schema ("etls", ...), so module tables can't collide or get mixed up.
    op.execute("CREATE SCHEMA IF NOT EXISTS core")


def downgrade() -> None:
    # No CASCADE on purpose: if tables still exist in core, refuse rather than
    # silently delete them. Later migrations drop their own tables first.
    op.execute("DROP SCHEMA core")
