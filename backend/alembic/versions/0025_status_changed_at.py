"""When a case entered its current status, for queues ("days waiting").

Revision ID: 0025
Revises: 0024
Create Date: 2026-10-20

core.cases.updated_at happens to change only with the status today, but drafts
(chunk 2) will update a case without moving it. A queue's "waiting since" must
not reset when someone edits a form, so it gets its own column, set only by
the engine when it opens a case or changes its status.
"""
import sqlalchemy as sa
from alembic import op

revision = "0025"
down_revision = "0024"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "cases",
        sa.Column("status_changed_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        schema="core",
    )
    op.execute("UPDATE core.cases SET status_changed_at = updated_at")
    # Queues look cases up by status and sort by how long they've waited.
    op.create_index("cases_status_idx", "cases", ["current_status_id", "status_changed_at"], schema="core")


def downgrade() -> None:
    op.drop_index("cases_status_idx", "cases", schema="core")
    op.drop_column("cases", "status_changed_at", schema="core")
