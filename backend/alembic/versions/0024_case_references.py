"""Case reference numbers: a sequence per service per year, e.g. MOTIE/ETLS/FL/2026/0001.

Revision ID: 0024
Revises: 0023
Create Date: 2026-10-20

- core.workflows.reference_prefix: "MOTIE/ETLS/FL" for facility letters,
  "MOTIE/ETLS/AP" for approvals. [CONFIRM] the format (SCREENS.md global rules).
- core.reference_counters: the last number used per workflow per year. The next
  number is taken with one upsert that locks the counter row, so two
  submissions at the same moment queue for it, and a submission that rolls
  back gives its number back (no gaps).
- core.cases.reference and submitted_at: set when the applicant submits (today
  that's when the case is opened; with drafts in chunk 2, on "Submit").

This is the tracking number for applicants and staff. The registry file
reference printed on the facility letter is a separate setting.
"""
import sqlalchemy as sa
from alembic import op

revision = "0024"
down_revision = "0023"
branch_labels = None
depends_on = None

APP_ROLE = "motie_app"
PREFIXES = {"etls_facility_letter": "MOTIE/ETLS/FL", "etls_application": "MOTIE/ETLS/AP"}


def upgrade() -> None:
    op.add_column("workflows", sa.Column("reference_prefix", sa.Text), schema="core")
    for code, prefix in PREFIXES.items():
        op.execute(f"UPDATE core.workflows SET reference_prefix = '{prefix}' WHERE code = '{code}'")
    # Every workflow must say how its cases are numbered.
    op.alter_column("workflows", "reference_prefix", nullable=False, schema="core")
    op.create_unique_constraint("workflows_reference_prefix_key", "workflows", ["reference_prefix"], schema="core")

    op.create_table(
        "reference_counters",
        sa.Column("workflow_id", sa.SmallInteger, sa.ForeignKey("core.workflows.id"), primary_key=True),
        sa.Column("year", sa.SmallInteger, primary_key=True),
        sa.Column("last_number", sa.Integer, nullable=False),
        sa.CheckConstraint("last_number > 0", name="reference_counters_positive"),
        schema="core",
    )

    # Null until submitted (drafts, from chunk 2, have no reference yet).
    op.add_column("cases", sa.Column("reference", sa.Text), schema="core")
    op.add_column("cases", sa.Column("submitted_at", sa.DateTime(timezone=True)), schema="core")
    op.create_unique_constraint("cases_reference_key", "cases", ["reference"], schema="core")
    op.create_check_constraint(
        "cases_reference_with_date", "cases", "(reference IS NULL) = (submitted_at IS NULL)", schema="core"
    )

    # Existing cases (dev only) get numbers in the order they were opened.
    op.execute(
        """
        UPDATE core.cases c SET reference = n.reference, submitted_at = c.created_at
        FROM (
            SELECT c2.id, w.reference_prefix || '/' || extract(year FROM c2.created_at)::int || '/'
                   || lpad(row_number() OVER (
                          PARTITION BY c2.workflow_id, extract(year FROM c2.created_at)
                          ORDER BY c2.created_at, c2.id)::text, 4, '0') AS reference
            FROM core.cases c2 JOIN core.workflows w ON w.id = c2.workflow_id
        ) n
        WHERE n.id = c.id
        """
    )
    op.execute(
        """
        INSERT INTO core.reference_counters (workflow_id, year, last_number)
        SELECT workflow_id, extract(year FROM created_at)::int, count(*)
        FROM core.cases GROUP BY 1, 2
        """
    )

    op.execute(f"GRANT SELECT, INSERT, UPDATE ON core.reference_counters TO {APP_ROLE}")


def downgrade() -> None:
    op.drop_constraint("cases_reference_with_date", "cases", schema="core")
    op.drop_constraint("cases_reference_key", "cases", schema="core")
    op.drop_column("cases", "submitted_at", schema="core")
    op.drop_column("cases", "reference", schema="core")
    op.drop_table("reference_counters", schema="core")
    op.drop_constraint("workflows_reference_prefix_key", "workflows", schema="core")
    op.drop_column("workflows", "reference_prefix", schema="core")
