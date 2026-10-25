"""Records dispatches signed letters to GRA; "Sent to GRA" is final; corrections.

Revision ID: 0030
Revises: 0029
Create Date: 2026-10-24

SCREENS.md S1 and C9: outgoing correspondence is Records' job.
- "Send to GRA" (signed -> sent_to_gra) moves from the ETLS desk to the
  Records post, renamed "Mark sent to GRA". It needs the dispatch date,
  recorded in etls.facility_letter_dispatches against the exact letter
  sent (check etls_dispatch_recorded). The ETLS endpoint
  POST /etls/facility-letters/{id}/sent-to-gra records both at once.
- "Sent to GRA" becomes final. The manual "Close the file" and the "closed"
  status go [CONFIRM: unless GRA reports back]. Refuses to run if a case is
  in "closed" (only possible on a dev database; reset it).
- core.transition_checks.in_dry_run: false for a check about something sent
  with the move itself (the dispatch date). The move still runs it, but the
  dry run behind `blocked_by` can't judge it, so leaves it out; otherwise
  the button would always look disabled.
- core.workflow_transitions.is_correction: a move that puts a mistake right
  (cancelling a signed letter). It may leave a final status, and it puts the
  case in nobody's queue: a signed letter isn't "work" for the PS just
  because the PS could cancel it.
- core.workflow_statuses.applicant_label_corrected: the timeline's wording
  when a case comes back to this status after a hidden correction took it
  away from there. "Sent to GRA" after a cancelled letter that GRA already
  had reads "Corrected letter issued" (decided 2026-10-24).
"""
import sqlalchemy as sa
from alembic import op

revision = "0030"
down_revision = "0029"
branch_labels = None
depends_on = None

APP_ROLE = "motie_app"

_FL = """
    FROM core.workflow_transitions x
    JOIN core.workflows w ON w.id = x.workflow_id AND w.code = 'etls_facility_letter'
    JOIN core.workflow_statuses f ON f.id = x.from_status_id
    JOIN core.workflow_statuses t ON t.id = x.to_status_id
"""
_SEND = f"SELECT x.id {_FL} WHERE f.code = 'signed' AND t.code = 'sent_to_gra'"
_CLOSE = f"SELECT x.id {_FL} WHERE f.code = 'sent_to_gra' AND t.code = 'closed'"


def _status_sql(column: str, value: str, code: str) -> str:
    return f"""
        UPDATE core.workflow_statuses s SET {column} = {value}
        FROM core.workflows w
        WHERE s.workflow_id = w.id AND w.code = 'etls_facility_letter' AND s.code = '{code}'
    """


def upgrade() -> None:
    conn = op.get_bind()
    closed = conn.execute(
        sa.text(
            "SELECT count(*) FROM core.cases c JOIN core.workflow_statuses s ON s.id = c.current_status_id "
            "JOIN core.workflows w ON w.id = s.workflow_id "
            "WHERE w.code = 'etls_facility_letter' AND s.code = 'closed'"
        )
    ).scalar()
    if closed:
        raise RuntimeError(
            "Can't remove the 'closed' status: some facility letter cases are in it. "
            "On a dev database, run scripts/reset-dev.sh."
        )

    op.add_column(
        "workflow_transitions",
        sa.Column("is_correction", sa.Boolean, nullable=False, server_default=sa.false()),
        schema="core",
    )
    op.add_column("workflow_statuses", sa.Column("applicant_label_corrected", sa.Text), schema="core")
    op.add_column(
        "transition_checks",
        sa.Column("in_dry_run", sa.Boolean, nullable=False, server_default=sa.true()),
        schema="core",
    )

    # One statement per execute(): asyncpg refuses several in one.
    op.execute(f"DELETE FROM core.transition_checks WHERE transition_id IN ({_CLOSE})")
    op.execute(f"DELETE FROM core.transition_effects WHERE transition_id IN ({_CLOSE})")
    op.execute(f"DELETE FROM core.workflow_transitions WHERE id IN ({_CLOSE})")
    op.execute(
        """
        DELETE FROM core.workflow_statuses s USING core.workflows w
        WHERE s.workflow_id = w.id AND w.code = 'etls_facility_letter' AND s.code = 'closed'
        """
    )
    op.execute(_status_sql("is_final", "true", "sent_to_gra"))
    op.execute(_status_sql("applicant_label_corrected", "'Corrected letter issued'", "sent_to_gra"))

    op.execute(
        f"""
        UPDATE core.workflow_transitions
        SET name = 'Mark sent to GRA',
            required_position_id = (SELECT id FROM core.positions WHERE code = 'records_officer')
        WHERE id IN ({_SEND})
        """
    )
    op.execute(
        "INSERT INTO core.transition_checks (transition_id, check_code, in_dry_run) "
        f"SELECT id, 'etls_dispatch_recorded', false FROM ({_SEND}) s"
    )
    op.execute(
        f"""
        UPDATE core.workflow_transitions SET is_correction = true
        WHERE id IN (SELECT x.id {_FL} WHERE x.name = 'Cancel the signed letter')
        """
    )

    # One row per letter sent: which issued letter, and the day it went.
    op.create_table(
        "facility_letter_dispatches",
        sa.Column("id", sa.BigInteger, sa.Identity(), primary_key=True),
        sa.Column("case_id", sa.BigInteger, sa.ForeignKey("etls.facility_letters.case_id"), nullable=False),
        sa.Column(
            "issued_document_id",
            sa.BigInteger,
            sa.ForeignKey("core.issued_documents.id"),
            nullable=False,
            unique=True,  # a letter is sent once
        ),
        sa.Column("dispatched_on", sa.Date, nullable=False),
        sa.Column("recorded_by", sa.BigInteger, sa.ForeignKey("core.users.id"), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        schema="etls",
    )
    op.create_index("facility_letter_dispatches_case_idx", "facility_letter_dispatches", ["case_id"], schema="etls")
    op.execute(f"GRANT SELECT, INSERT ON etls.facility_letter_dispatches TO {APP_ROLE}")


def downgrade() -> None:
    op.drop_table("facility_letter_dispatches", schema="etls")
    op.execute("DELETE FROM core.transition_checks WHERE check_code = 'etls_dispatch_recorded'")
    op.execute(
        f"""
        UPDATE core.workflow_transitions
        SET name = 'Send to GRA',
            required_position_id = (SELECT id FROM core.positions WHERE code = 'etls_desk_officer')
        WHERE id IN ({_SEND})
        """
    )
    op.execute(_status_sql("is_final", "false", "sent_to_gra"))
    op.execute(
        """
        INSERT INTO core.workflow_statuses (workflow_id, code, name, is_final, applicant_label, applicant_explanation)
        SELECT w.id, 'closed', 'Closed', true, 'Letter sent to GRA',
               'Your facility letter has been sent to the Gambia Revenue Authority.'
        FROM core.workflows w WHERE w.code = 'etls_facility_letter'
        """
    )
    op.execute(
        """
        INSERT INTO core.workflow_transitions (workflow_id, from_status_id, to_status_id, required_position_id, name)
        SELECT w.id, f.id, t.id, p.id, 'Close the file'
        FROM core.workflows w
        JOIN core.workflow_statuses f ON f.workflow_id = w.id AND f.code = 'sent_to_gra'
        JOIN core.workflow_statuses t ON t.workflow_id = w.id AND t.code = 'closed'
        JOIN core.positions p ON p.code = 'etls_desk_officer'
        WHERE w.code = 'etls_facility_letter'
        """
    )
    op.drop_column("transition_checks", "in_dry_run", schema="core")
    op.drop_column("workflow_statuses", "applicant_label_corrected", schema="core")
    op.drop_column("workflow_transitions", "is_correction", schema="core")
