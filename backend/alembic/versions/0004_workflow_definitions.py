"""Workflow definitions: workflows, their statuses, and allowed transitions.

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-18
"""
import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # workflows: one row per process (e.g. "ETLS application"). start_role_id is
    # the role allowed to open a new case of this kind.
    op.create_table(
        "workflows",
        sa.Column("id", sa.SmallInteger, sa.Identity(), primary_key=True),
        sa.Column("code", sa.Text, nullable=False, unique=True),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("start_role_id", sa.SmallInteger, sa.ForeignKey("core.roles.id"), nullable=False),
        schema="core",
    )

    # workflow_statuses: the steps a case can be in, per workflow.
    op.create_table(
        "workflow_statuses",
        sa.Column("id", sa.Integer, sa.Identity(), primary_key=True),
        sa.Column("workflow_id", sa.SmallInteger, sa.ForeignKey("core.workflows.id"), nullable=False),
        sa.Column("code", sa.Text, nullable=False),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("is_initial", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("is_final", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.UniqueConstraint("workflow_id", "code", name="workflow_statuses_workflow_code_key"),
        # (workflow_id, id) is unique anyway because id is. Declaring it lets other
        # tables reference the *pair*, which is how we stop a transition or a case
        # from using a status that belongs to a different workflow.
        sa.UniqueConstraint("workflow_id", "id", name="workflow_statuses_workflow_id_id_key"),
        sa.CheckConstraint("NOT (is_initial AND is_final)", name="workflow_statuses_not_both"),
        schema="core",
    )
    # A partial unique index: uniqueness applies only to rows WHERE is_initial.
    # Result: at most one starting status per workflow.
    op.create_index(
        "workflow_statuses_one_initial",
        "workflow_statuses",
        ["workflow_id"],
        unique=True,
        postgresql_where=sa.text("is_initial"),
        schema="core",
    )

    # workflow_transitions: the allowed moves. Each row says "a user with
    # required_role may move a case from from_status to to_status". The same move
    # can be allowed for several roles by adding one row per role.
    op.create_table(
        "workflow_transitions",
        sa.Column("id", sa.Integer, sa.Identity(), primary_key=True),
        sa.Column("workflow_id", sa.SmallInteger, nullable=False),
        sa.Column("from_status_id", sa.Integer, nullable=False),
        sa.Column("to_status_id", sa.Integer, nullable=False),
        sa.Column("required_role_id", sa.SmallInteger, sa.ForeignKey("core.roles.id"), nullable=False),
        sa.Column("name", sa.Text, nullable=False),  # the button label, e.g. "Forward to Minister"
        sa.ForeignKeyConstraint(
            ["workflow_id", "from_status_id"],
            ["core.workflow_statuses.workflow_id", "core.workflow_statuses.id"],
            name="workflow_transitions_from_fkey",
        ),
        sa.ForeignKeyConstraint(
            ["workflow_id", "to_status_id"],
            ["core.workflow_statuses.workflow_id", "core.workflow_statuses.id"],
            name="workflow_transitions_to_fkey",
        ),
        sa.UniqueConstraint(
            "from_status_id", "to_status_id", "required_role_id", name="workflow_transitions_move_key"
        ),
        sa.CheckConstraint("from_status_id <> to_status_id", name="workflow_transitions_no_self_loop"),
        schema="core",
    )


def downgrade() -> None:
    op.drop_table("workflow_transitions", schema="core")
    op.drop_table("workflow_statuses", schema="core")  # drops its index too
    op.drop_table("workflows", schema="core")
