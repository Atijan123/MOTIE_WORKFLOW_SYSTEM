"""Case flags: something about a case needs a named post's attention.

Revision ID: 0016
Revises: 0015
Create Date: 2026-10-19

A flag is addressed to a post (e.g. the ETLS desk). While a *blocking* flag is
open, the engine refuses every status change on the case, until a holder of
that post resolves it with a written reason. First use: a certificate of origin
number that was used on an earlier case (step 6b).
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None

APP_ROLE = "motie_app"


def upgrade() -> None:
    op.create_table(
        "case_flags",
        sa.Column("id", sa.BigInteger, sa.Identity(), primary_key=True),
        sa.Column("case_id", sa.BigInteger, sa.ForeignKey("core.cases.id"), nullable=False),
        # What kind of flag, for code and reports, e.g. "etls.duplicate_certificate_of_origin".
        sa.Column("code", sa.Text, nullable=False),
        sa.Column("message", sa.Text, nullable=False),  # what a person reads
        sa.Column("details", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("for_position_id", sa.SmallInteger, sa.ForeignKey("core.positions.id"), nullable=False),
        sa.Column("blocking", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column(
            "raised_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        # Empty when the system raised it (e.g. the duplicate check).
        sa.Column("raised_by", sa.BigInteger, sa.ForeignKey("core.users.id"), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolved_by", sa.BigInteger, sa.ForeignKey("core.users.id"), nullable=True),
        sa.Column("resolution", sa.Text, nullable=True),
        sa.CheckConstraint(
            "(resolved_at IS NULL) = (resolved_by IS NULL) AND (resolved_at IS NULL) = (resolution IS NULL)",
            name="case_flags_resolved_complete",
        ),
        schema="core",
    )
    # Asked before every status change: "does this case have open flags?"
    op.create_index(
        "case_flags_open_idx",
        "case_flags",
        ["case_id"],
        postgresql_where=sa.text("resolved_at IS NULL"),
        schema="core",
    )

    op.execute(f"GRANT SELECT, INSERT ON core.case_flags TO {APP_ROLE}")
    # Resolving fills in the resolution; nothing else about a flag may change.
    op.execute(
        f"GRANT UPDATE (resolved_at, resolved_by, resolution) ON core.case_flags TO {APP_ROLE}"
    )


def downgrade() -> None:
    op.drop_table("case_flags", schema="core")
