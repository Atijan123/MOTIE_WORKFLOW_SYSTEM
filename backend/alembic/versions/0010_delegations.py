"""Delegations: a post's holder lets another post act for it, for a date range.

Revision ID: 0010
Revises: 0009
Create Date: 2026-10-19

Example: the Minister travels from 3 to 10 March, so the Minister's post
delegates to the Permanent Secretary's post for those dates. Whoever holds the
PS post may then make the Minister's moves, and the audit log says they acted
on the Minister's behalf.
"""
import sqlalchemy as sa
from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None

APP_ROLE = "motie_app"


def upgrade() -> None:
    op.create_table(
        "delegations",
        sa.Column("id", sa.BigInteger, sa.Identity(), primary_key=True),
        sa.Column("from_position_id", sa.SmallInteger, sa.ForeignKey("core.positions.id"), nullable=False),
        sa.Column("to_position_id", sa.SmallInteger, sa.ForeignKey("core.positions.id"), nullable=False),
        # Empty = every workflow; otherwise only cases of this workflow.
        sa.Column("workflow_id", sa.SmallInteger, sa.ForeignKey("core.workflows.id"), nullable=True),
        # Whole days, both included, in Ministry time (see delegation.py today()).
        sa.Column("starts_on", sa.Date, nullable=False),
        sa.Column("ends_on", sa.Date, nullable=False),
        sa.Column("reason", sa.Text, nullable=True),
        sa.Column("created_by", sa.BigInteger, sa.ForeignKey("core.users.id"), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        # A delegation is ended early by revoking it, never by deleting it, so
        # audit rows that point at it always find it.
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_by", sa.BigInteger, sa.ForeignKey("core.users.id"), nullable=True),
        sa.CheckConstraint("from_position_id <> to_position_id", name="delegations_not_to_self"),
        sa.CheckConstraint("starts_on <= ends_on", name="delegations_dates_in_order"),
        sa.CheckConstraint(
            "(revoked_at IS NULL) = (revoked_by IS NULL)", name="delegations_revoked_complete"
        ),
        schema="core",
    )
    # The engine asks "which posts may this user act for today?" on status
    # changes: look up by the receiving post, then by date.
    op.create_index(
        "delegations_to_position_idx", "delegations", ["to_position_id", "ends_on"], schema="core"
    )

    op.execute(f"GRANT SELECT, INSERT ON core.delegations TO {APP_ROLE}")
    # Column-level grant: the app can revoke a delegation, but can't change its
    # posts or dates after the fact (e.g. stretch it to cover a past action).
    op.execute(f"GRANT UPDATE (revoked_at, revoked_by) ON core.delegations TO {APP_ROLE}")


def downgrade() -> None:
    op.drop_table("delegations", schema="core")
