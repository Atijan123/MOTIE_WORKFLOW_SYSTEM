"""Returns: the Ministry sends an application back with a message; the applicant resubmits.

Revision ID: 0027
Revises: 0026
Create Date: 2026-10-24

A return carries two texts (SCREENS.md global rules):
- a **message to the applicant**, shown to them on the case, in their list
  and on their timeline: the new `applicant_message` of a move;
- an optional **internal minute**, staff only: the move's existing `comment`.

- core.workflow_transitions.requires_applicant_message: the move needs the
  message (returns, and "Reject", whose reason the applicant sees).
- Facility letters: a status "returned" (editable by the applicant, like a
  draft), "Return to applicant" for Records (from submitted) and the desk
  (from originals_received), and the applicant's "Resubmit" (returned ->
  submitted, so a resubmitted case goes to Records first again). Resubmit has
  the same check and effects as Submit; it keeps the case's reference.
"""
import sqlalchemy as sa
from alembic import op

revision = "0027"
down_revision = "0026"
branch_labels = None
depends_on = None

RETURNS = [
    # (from status, post)
    ("submitted", "records_officer"),
    ("originals_received", "etls_desk_officer"),
]

_FL = "JOIN core.workflows w ON w.id = x.workflow_id AND w.code = 'etls_facility_letter'"
_RESUBMIT = f"""
    FROM core.workflow_transitions x {_FL}
    JOIN core.workflow_statuses f ON f.id = x.from_status_id AND f.code = 'returned'
"""


def upgrade() -> None:
    op.add_column(
        "workflow_transitions",
        sa.Column("requires_applicant_message", sa.Boolean, nullable=False, server_default=sa.false()),
        schema="core",
    )
    op.execute(
        """
        INSERT INTO core.workflow_statuses
            (workflow_id, code, name, applicant_editable, applicant_label, applicant_explanation)
        SELECT w.id, 'returned', 'Returned to the applicant', true, 'Returned: action needed',
               'The Ministry has sent your application back. Read the message, correct it, and submit it again.'
        FROM core.workflows w WHERE w.code = 'etls_facility_letter'
        """
    )
    for from_code, post in RETURNS:
        op.execute(
            f"""
            INSERT INTO core.workflow_transitions
                (workflow_id, from_status_id, to_status_id, required_position_id, name, requires_applicant_message)
            SELECT w.id, f.id, t.id, p.id, 'Return to applicant', true
            FROM core.workflows w
            JOIN core.workflow_statuses f ON f.workflow_id = w.id AND f.code = '{from_code}'
            JOIN core.workflow_statuses t ON t.workflow_id = w.id AND t.code = 'returned'
            JOIN core.positions p ON p.code = '{post}'
            WHERE w.code = 'etls_facility_letter'
            """
        )
    op.execute(
        """
        INSERT INTO core.workflow_transitions
            (workflow_id, from_status_id, to_status_id, required_position_id, by_applicant, name, applicant_event)
        SELECT w.id, f.id, t.id, NULL, true, 'Resubmit', 'Resubmitted'
        FROM core.workflows w
        JOIN core.workflow_statuses f ON f.workflow_id = w.id AND f.code = 'returned'
        JOIN core.workflow_statuses t ON t.workflow_id = w.id AND t.code = 'submitted'
        WHERE w.code = 'etls_facility_letter'
        """
    )
    op.execute(f"INSERT INTO core.transition_checks (transition_id, check_code) SELECT x.id, 'known_documents_complete' {_RESUBMIT}")
    op.execute(
        f"""
        INSERT INTO core.transition_effects (transition_id, effect_code)
        SELECT x.id, e.code {_RESUBMIT}
        CROSS JOIN (VALUES ('assign_reference'), ('etls_check_duplicate_certificates')) AS e(code)
        """
    )
    # The applicant is told why their application was rejected.
    op.execute(
        f"""
        UPDATE core.workflow_transitions x SET requires_applicant_message = true
        FROM core.workflows w
        WHERE x.workflow_id = w.id AND w.code = 'etls_facility_letter' AND x.name = 'Reject'
        """
    )


def downgrade() -> None:
    conn = op.get_bind()
    returned = conn.execute(
        sa.text(
            "SELECT count(*) FROM core.cases c JOIN core.workflow_statuses s ON s.id = c.current_status_id "
            "WHERE s.code = 'returned'"
        )
    ).scalar()
    if returned:
        raise RuntimeError("Can't downgrade 0027: some cases are returned to their applicants.")
    for table in ("transition_effects", "transition_checks"):
        op.execute(f"DELETE FROM core.{table} WHERE transition_id IN (SELECT x.id {_RESUBMIT})")
    op.execute(
        f"""
        DELETE FROM core.workflow_transitions WHERE id IN (
            SELECT x.id FROM core.workflow_transitions x {_FL}
            JOIN core.workflow_statuses s ON s.id IN (x.from_status_id, x.to_status_id) AND s.code = 'returned'
        )
        """
    )
    op.execute(
        """
        DELETE FROM core.workflow_statuses s USING core.workflows w
        WHERE s.workflow_id = w.id AND w.code = 'etls_facility_letter' AND s.code = 'returned'
        """
    )
    op.drop_column("workflow_transitions", "requires_applicant_message", schema="core")
