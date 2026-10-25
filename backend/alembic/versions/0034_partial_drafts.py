"""Partial drafts: a draft may be saved half-filled; Submit checks it's complete.

Revision ID: 0034
Revises: 0033
Create Date: 2026-10-25

Before, a draft needed every required field (decided in 8a), so an applicant
couldn't save and come back later. Now:
- the form's columns on etls.facility_letters may be empty (a draft);
- a certificate of origin on a draft may have no issue date yet;
- a new check etls_form_complete on Submit and Resubmit lists what is still
  empty, in the action's blocked_by, next to the missing documents.
So nothing past "submitted" can have an empty field: every later step (the
desk, the letter) reads a complete form, as before.
"""
import sqlalchemy as sa
from alembic import op

revision = "0034"
down_revision = "0033"
branch_labels = None
depends_on = None

FORM_COLUMNS = (
    "importer_name",
    "importer_address",
    "product",
    "quantity",
    "unit",
    "exporter_name",
    "exporter_country",
    "exporter_etls_approval_number",
)

_SUBMIT_MOVES = """
    FROM core.workflow_transitions x
    JOIN core.workflows w ON w.id = x.workflow_id AND w.code = 'etls_facility_letter'
    JOIN core.workflow_statuses f ON f.id = x.from_status_id AND f.code IN ('draft', 'returned')
    JOIN core.workflow_statuses t ON t.id = x.to_status_id AND t.code = 'submitted'
"""


def upgrade() -> None:
    for column in FORM_COLUMNS:
        op.alter_column("facility_letters", column, nullable=True, schema="etls")
    op.execute(
        f"""
        INSERT INTO core.transition_checks (transition_id, check_code)
        SELECT x.id, 'etls_form_complete' {_SUBMIT_MOVES}
        """
    )


def downgrade() -> None:
    conn = op.get_bind()
    empty = conn.execute(
        sa.text(
            "SELECT count(*) FROM etls.facility_letters WHERE "
            + " OR ".join(f"{c} IS NULL" for c in FORM_COLUMNS)
        )
    ).scalar()
    if empty:
        # Putting NOT NULL back would fail anyway; say why.
        raise RuntimeError("Can't downgrade 0034: some drafts have empty fields.")
    op.execute("DELETE FROM core.transition_checks WHERE check_code = 'etls_form_complete'")
    for column in FORM_COLUMNS:
        op.alter_column("facility_letters", column, nullable=False, schema="etls")
