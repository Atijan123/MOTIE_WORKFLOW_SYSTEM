"""The PS may return a verified file to the ETLS desk (SCREENS.md S3).

Revision ID: 0031
Revises: 0030
Create Date: 2026-10-25

"Return to the desk" (verified -> originals_received), for the PS or anyone
acting for the PS, with a written reason (the internal minute). Nothing has
been signed yet, so there is no letter to cancel. The applicant's timeline
shows "Being verified" again, which is true.
"""
from alembic import op

revision = "0031"
down_revision = "0030"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        INSERT INTO core.workflow_transitions
            (workflow_id, from_status_id, to_status_id, required_position_id, name, requires_comment)
        SELECT w.id, f.id, t.id, p.id, 'Return to the desk', true
        FROM core.workflows w
        JOIN core.workflow_statuses f ON f.workflow_id = w.id AND f.code = 'verified'
        JOIN core.workflow_statuses t ON t.workflow_id = w.id AND t.code = 'originals_received'
        JOIN core.positions p ON p.code = 'permanent_secretary'
        WHERE w.code = 'etls_facility_letter'
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DELETE FROM core.workflow_transitions x USING core.workflows w
        WHERE x.workflow_id = w.id AND w.code = 'etls_facility_letter' AND x.name = 'Return to the desk'
        """
    )
