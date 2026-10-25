"""The desk may return a case held by a duplicate flag, not only reject it.

Revision ID: 0037
Revises: 0036
Create Date: 2026-10-25

[CONFIRM] with the ETLS desk (like rejecting while held, C7). Before, the
desk had to resolve the flag with a finding, then return. Now its "Return to
applicant" is allowed on hold, as "Reject" is (0029): the engine resolves the
desk's open flags with the move's reason ("Return to applicant: ...").
When the applicant resubmits, the duplicate check runs again (the Submit
effect), so a number that is still used elsewhere raises a new flag and the
desk sees it again.
"""
from alembic import op

revision = "0037"
down_revision = "0036"
branch_labels = None
depends_on = None

_DESK_RETURN = """
    SELECT x.id FROM core.workflow_transitions x
    JOIN core.workflows w ON w.id = x.workflow_id AND w.code = 'etls_facility_letter'
    JOIN core.workflow_statuses f ON f.id = x.from_status_id AND f.code = 'originals_received'
    JOIN core.workflow_statuses t ON t.id = x.to_status_id AND t.code = 'returned'
"""


def upgrade() -> None:
    op.execute(f"UPDATE core.workflow_transitions SET allowed_on_hold = true WHERE id IN ({_DESK_RETURN})")


def downgrade() -> None:
    op.execute(f"UPDATE core.workflow_transitions SET allowed_on_hold = false WHERE id IN ({_DESK_RETURN})")
