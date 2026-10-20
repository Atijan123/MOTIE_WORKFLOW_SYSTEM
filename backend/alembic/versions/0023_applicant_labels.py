"""What applicants see: a plain label (and one-line explanation) for every status.

Revision ID: 0023
Revises: 0022
Create Date: 2026-10-20

Applicants never see internal step names ("originals_received") or staff
wording ("Originals received by Records"). Each status gets:
- applicant_label (required): e.g. "Being verified";
- applicant_explanation (optional): one line, e.g. "Bring the original
  certificate of origin to Records."

Each move may also say how the applicant's timeline describes it:
- applicant_event: e.g. Records' accept reads "Originals checked", although
  the case then shows "Being verified". Empty = the new status's label.
- applicant_visible: false hides the move from the applicant's timeline
  (cancelling a signed letter: the case simply shows "Being verified" again).

Facility letter labels come from docs/SCREENS.md (A2). "Draft" and
"Returned: action needed" arrive with those statuses in chunk 2. The
explanations are placeholders [CONFIRM] with the ETLS desk.
"""
import sqlalchemy as sa
from alembic import op

revision = "0023"
down_revision = "0022"
branch_labels = None
depends_on = None

LABELS = {
    "etls_facility_letter": [
        ("submitted", "Submitted", "Bring the original certificate of origin to Records."),
        ("originals_received", "Being verified", "The ETLS desk is checking your application."),
        ("verified", "Awaiting signature", "Your application is verified and waiting for the Permanent Secretary's signature."),
        ("signed", "Letter signed", "Your facility letter is signed and will be sent to GRA."),
        ("sent_to_gra", "Letter sent to GRA", "Your facility letter has been sent to the Gambia Revenue Authority."),
        ("closed", "Letter sent to GRA", "Your facility letter has been sent to the Gambia Revenue Authority."),
        ("rejected", "Rejected", "Your application was not accepted."),
    ],
    # Being retired in chunk 3; labels follow SCREENS.md A5 as far as its steps go.
    "etls_application": [
        ("submitted", "Submitted", None),
        ("with_minister", "Accepted by the Ministry", None),
        ("with_ps", "Accepted by the Ministry", None),
        ("with_director", "Accepted by the Ministry", None),
        ("with_officer", "Technical review", None),
        ("approved", "Approved", None),
        ("rejected", "Rejected", None),
    ],
}


def _quote(value: str | None) -> str:
    return "NULL" if value is None else "'" + value.replace("'", "''") + "'"


def upgrade() -> None:
    op.add_column("workflow_statuses", sa.Column("applicant_label", sa.Text), schema="core")
    op.add_column("workflow_statuses", sa.Column("applicant_explanation", sa.Text), schema="core")
    op.add_column("workflow_transitions", sa.Column("applicant_event", sa.Text), schema="core")
    op.add_column(
        "workflow_transitions",
        sa.Column("applicant_visible", sa.Boolean, nullable=False, server_default=sa.true()),
        schema="core",
    )

    for workflow, rows in LABELS.items():
        for code, label, explanation in rows:
            op.execute(
                f"""
                UPDATE core.workflow_statuses s
                SET applicant_label = {_quote(label)}, applicant_explanation = {_quote(explanation)}
                FROM core.workflows w
                WHERE s.workflow_id = w.id AND w.code = '{workflow}' AND s.code = '{code}'
                """
            )
    # Required from now on: a status without a label would show applicants nothing,
    # or tempt someone to fall back to the internal name. Fails here if one was missed.
    op.alter_column("workflow_statuses", "applicant_label", nullable=False, schema="core")

    op.execute(
        """
        UPDATE core.workflow_transitions x SET applicant_event = 'Originals checked'
        FROM core.workflows w, core.workflow_statuses f, core.workflow_statuses t
        WHERE x.workflow_id = w.id AND w.code = 'etls_facility_letter'
          AND f.id = x.from_status_id AND f.code = 'submitted'
          AND t.id = x.to_status_id AND t.code = 'originals_received'
        """
    )
    op.execute(
        """
        UPDATE core.workflow_transitions x SET applicant_visible = false
        FROM core.workflows w
        WHERE x.workflow_id = w.id AND w.code = 'etls_facility_letter'
          AND x.name = 'Cancel the signed letter'
        """
    )


def downgrade() -> None:
    op.drop_column("workflow_transitions", "applicant_visible", schema="core")
    op.drop_column("workflow_transitions", "applicant_event", schema="core")
    op.drop_column("workflow_statuses", "applicant_explanation", schema="core")
    op.drop_column("workflow_statuses", "applicant_label", schema="core")
