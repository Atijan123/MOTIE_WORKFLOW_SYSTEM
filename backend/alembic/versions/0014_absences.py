"""Absence records: a post holder is away from one date to another.

Revision ID: 0014
Revises: 0013
Create Date: 2026-10-19

The holder records their own absence, or an authorised officer records it for
them. The audit log keeps who recorded it. While every holder of a post is
absent, the succession order (0013) decides who acts for the post (step 5d).
"""
import sqlalchemy as sa
from alembic import op

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None

APP_ROLE = "motie_app"


def upgrade() -> None:
    op.create_table(
        "absences",
        sa.Column("id", sa.BigInteger, sa.Identity(), primary_key=True),
        # The person who is away. Absence belongs to the person, not to one post:
        # someone on leave is away from every post they hold.
        sa.Column("user_id", sa.BigInteger, sa.ForeignKey("core.users.id"), nullable=False),
        # Whole days, both included, in Ministry time (see delegation.py today()).
        sa.Column("starts_on", sa.Date, nullable=False),
        sa.Column("ends_on", sa.Date, nullable=False),
        sa.Column("reason", sa.Text, nullable=True),
        # The same as user_id when people record their own absence.
        sa.Column("recorded_by", sa.BigInteger, sa.ForeignKey("core.users.id"), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        # Ended early (back at work) by cancelling, never by deleting or editing,
        # because audit rows point at absence ids.
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_by", sa.BigInteger, sa.ForeignKey("core.users.id"), nullable=True),
        sa.CheckConstraint("starts_on <= ends_on", name="absences_dates_in_order"),
        sa.CheckConstraint(
            "(cancelled_at IS NULL) = (cancelled_by IS NULL)", name="absences_cancelled_complete"
        ),
        schema="core",
    )
    # "Is this holder away today?" is asked on status changes.
    op.create_index("absences_user_idx", "absences", ["user_id", "ends_on"], schema="core")

    # [CONFIRM] Who may record an absence on someone else's behalf. Placeholder:
    # anyone given this role (e.g. the Minister's private secretary, HR).
    op.execute(
        "INSERT INTO core.roles (code, name) VALUES ('absence_recorder', 'Records absences for others')"
    )

    op.execute(f"GRANT SELECT, INSERT ON core.absences TO {APP_ROLE}")
    # Like delegations: the app may cancel an absence, never move its dates.
    op.execute(f"GRANT UPDATE (cancelled_at, cancelled_by) ON core.absences TO {APP_ROLE}")


def downgrade() -> None:
    op.drop_table("absences", schema="core")
    # Fails if a user still has the role; take it away first rather than lose that silently.
    op.execute("DELETE FROM core.roles WHERE code = 'absence_recorder'")
