"""Cases: the files that move through a workflow.

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-18
"""
import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # One row per file. current_status_id is where the file is now; how it got
    # there is in core.audit_log. Modules (e.g. etls) will keep their own details
    # in their own tables, pointing at core.cases.id.
    op.create_table(
        "cases",
        sa.Column("id", sa.BigInteger, sa.Identity(), primary_key=True),
        sa.Column("workflow_id", sa.SmallInteger, nullable=False),
        sa.Column("current_status_id", sa.Integer, nullable=False),
        sa.Column("created_by", sa.BigInteger, sa.ForeignKey("core.users.id"), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        # Same pair trick as transitions: the case's status must belong to the
        # case's own workflow.
        sa.ForeignKeyConstraint(
            ["workflow_id", "current_status_id"],
            ["core.workflow_statuses.workflow_id", "core.workflow_statuses.id"],
            name="cases_status_fkey",
        ),
        schema="core",
    )
    # "Which cases did this applicant open?" is asked on every applicant page.
    op.create_index("cases_created_by_idx", "cases", ["created_by"], schema="core")


def downgrade() -> None:
    op.drop_table("cases", schema="core")
