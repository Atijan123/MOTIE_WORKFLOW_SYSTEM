"""The HS code is optional on the form: Records checks only the documents known to be needed.

Revision ID: 0021
Revises: 0020
Create Date: 2026-10-20

An applicant may now leave out the HS code. Until the ETLS desk enters it,
nobody can tell whether the cement receipt is needed. So Records' move
("Confirm originals received") uses known_documents_complete, which waits on
undecided documents. The desk's "Verify" keeps the strict documents_complete
and hs_code_confirmed, so the receipt is decided and checked before the PS signs.

No column changes: etls.facility_letters.hs_code was already nullable (0020).
"""
from alembic import op

revision = "0021"
down_revision = "0020"
branch_labels = None
depends_on = None

_RECORDS_MOVE = """
    UPDATE core.transition_checks c SET check_code = '{new}'
    FROM core.workflow_transitions x
    JOIN core.workflows w ON w.id = x.workflow_id AND w.code = 'etls_facility_letter'
    JOIN core.workflow_statuses f ON f.id = x.from_status_id AND f.code = 'submitted'
    JOIN core.workflow_statuses t ON t.id = x.to_status_id AND t.code = 'originals_received'
    WHERE c.transition_id = x.id AND c.check_code = '{old}'
"""


def upgrade() -> None:
    op.execute(_RECORDS_MOVE.format(old="documents_complete", new="known_documents_complete"))


def downgrade() -> None:
    op.execute(_RECORDS_MOVE.format(old="known_documents_complete", new="documents_complete"))
