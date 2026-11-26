"""Records hands the applicant their copy of the letter (step 13b).

Revision ID: 0046
Revises: 0045
Create Date: 2026-11-26

In the office there's no applicant portal, so nobody downloads the
applicant's copy: Records prints it and hands it over. These two columns on
the applicant's copy record that, so the Outgoing tab can list the copies
still to hand over, and the file shows who handed it over and when.
"""
import sqlalchemy as sa
from alembic import op

revision = "0046"
down_revision = "0045"
branch_labels = None
depends_on = None

APP_ROLE = "motie_app"


def upgrade() -> None:
    op.add_column("facility_letter_copies", sa.Column("handed_over_at", sa.DateTime(timezone=True)), schema="etls")
    op.add_column(
        "facility_letter_copies",
        sa.Column("handed_over_by", sa.BigInteger, sa.ForeignKey("core.users.id")),
        schema="etls",
    )
    op.create_check_constraint(
        "facility_letter_copies_handed_over_together",
        "facility_letter_copies",
        "(handed_over_at IS NULL) = (handed_over_by IS NULL)",
        schema="etls",
    )
    # Only these two columns, and only on the applicant's copy (letter.py checks it).
    op.execute(f"GRANT UPDATE (handed_over_at, handed_over_by) ON etls.facility_letter_copies TO {APP_ROLE}")


def downgrade() -> None:
    op.drop_constraint("facility_letter_copies_handed_over_together", "facility_letter_copies", schema="etls")
    op.drop_column("facility_letter_copies", "handed_over_by", schema="etls")
    op.drop_column("facility_letter_copies", "handed_over_at", schema="etls")
