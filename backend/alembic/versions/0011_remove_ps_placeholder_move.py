"""Remove the placeholder "PS makes the Minister's move" transition.

Revision ID: 0011
Revises: 0010
Create Date: 2026-10-19

Migration 0005 let the Permanent Secretary always make the Minister's move, as a
stand-in for "the PS acts when the Minister is away". Delegation (0010) now does
this properly: the Minister's post delegates to the PS post for the dates of the
absence, and the audit log records that the PS acted on the Minister's behalf.

Cases are unaffected: they point at statuses, not transitions, and past audit
rows keep the transition name they recorded.
"""
from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        DELETE FROM core.workflow_transitions x
        USING core.workflows w, core.workflow_statuses f, core.workflow_statuses t, core.positions p
        WHERE w.code = 'etls_application' AND x.workflow_id = w.id
          AND f.id = x.from_status_id AND f.code = 'with_minister'
          AND t.id = x.to_status_id AND t.code = 'with_directorate'
          AND p.id = x.required_position_id AND p.code = 'permanent_secretary'
        """
    )


def downgrade() -> None:
    op.execute(
        """
        INSERT INTO core.workflow_transitions
            (workflow_id, from_status_id, to_status_id, required_position_id, name)
        SELECT w.id, f.id, t.id, p.id, 'Minute to the Directorate (for the Minister)'
        FROM core.workflows w
        JOIN core.workflow_statuses f ON f.workflow_id = w.id AND f.code = 'with_minister'
        JOIN core.workflow_statuses t ON t.workflow_id = w.id AND t.code = 'with_directorate'
        JOIN core.positions p ON p.code = 'permanent_secretary'
        WHERE w.code = 'etls_application'
        """
    )
