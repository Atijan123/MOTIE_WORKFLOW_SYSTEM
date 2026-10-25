"""Walk-ins: Records opens an application for an applicant who came in person.

Revision ID: 0032
Revises: 0031
Create Date: 2026-10-25

SCREENS.md global rules: "Records can create any application on behalf of an
applicant; recorded as such."
- core.workflows.walk_in_position_id: the post whose holders may open this
  workflow's cases for an applicant (Records, for facility letters). Empty =
  no walk-ins.
- core.cases.entered_by: the staff member who typed it in. The case still
  belongs to the applicant (created_by): it's in their list, they're told of
  each step, and they may finish it online. Holders of the walk-in post may
  make the applicant's moves on it (edit the draft, submit, resubmit); each
  such move's audit row says it was done for the applicant.
"""
import sqlalchemy as sa
from alembic import op

revision = "0032"
down_revision = "0031"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "workflows",
        sa.Column("walk_in_position_id", sa.SmallInteger, sa.ForeignKey("core.positions.id")),
        schema="core",
    )
    op.add_column("cases", sa.Column("entered_by", sa.BigInteger, sa.ForeignKey("core.users.id")), schema="core")
    op.execute(
        """
        UPDATE core.workflows SET walk_in_position_id = (SELECT id FROM core.positions WHERE code = 'records_officer')
        WHERE code = 'etls_facility_letter'
        """
    )


def downgrade() -> None:
    op.drop_column("cases", "entered_by", schema="core")
    op.drop_column("workflows", "walk_in_position_id", schema="core")
