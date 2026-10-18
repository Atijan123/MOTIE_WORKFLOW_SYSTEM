"""Append-only audit log.

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-18
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # One row per event: who (actor_user_id) did what (action) to which record
    # (entity_type + entity_id), when (occurred_at), plus any extra facts (details).
    # actor_user_id is empty for events the system does by itself.
    op.create_table(
        "audit_log",
        sa.Column("id", sa.BigInteger, sa.Identity(), primary_key=True),
        sa.Column(
            "occurred_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("actor_user_id", sa.BigInteger, sa.ForeignKey("core.users.id"), nullable=True),
        sa.Column("action", sa.Text, nullable=False),
        sa.Column("entity_type", sa.Text, nullable=False),
        # Text, so any module's records can be logged whatever their key type.
        sa.Column("entity_id", sa.Text, nullable=False),
        sa.Column("details", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        schema="core",
    )
    # Speeds up "show the history of this record", the most common question.
    op.create_index(
        "audit_log_entity_idx",
        "audit_log",
        ["entity_type", "entity_id", "occurred_at"],
        schema="core",
    )

    # The database itself refuses to change or remove audit rows. A trigger is a
    # function Postgres runs automatically on certain statements; this one just
    # raises an error, which cancels the UPDATE/DELETE/TRUNCATE.
    op.execute(
        """
        CREATE FUNCTION core.audit_log_block_changes() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'core.audit_log is append-only: % is not allowed', TG_OP;
        END
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER audit_log_no_update_delete
        BEFORE UPDATE OR DELETE ON core.audit_log
        FOR EACH ROW EXECUTE FUNCTION core.audit_log_block_changes()
        """
    )
    op.execute(
        """
        CREATE TRIGGER audit_log_no_truncate
        BEFORE TRUNCATE ON core.audit_log
        FOR EACH STATEMENT EXECUTE FUNCTION core.audit_log_block_changes()
        """
    )


def downgrade() -> None:
    # Dropping the table drops its triggers and index with it.
    op.drop_table("audit_log", schema="core")
    op.execute("DROP FUNCTION core.audit_log_block_changes()")
