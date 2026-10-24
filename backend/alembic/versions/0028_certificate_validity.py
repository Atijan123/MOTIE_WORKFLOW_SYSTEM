"""Certificate of origin issue dates, the six-month rule, and warning-only checks.

Revision ID: 0028
Revises: 0027
Create Date: 2026-10-24

A certificate of origin is valid for six months from its issue date. The
Ministry's rule (2026-10-24):
- the desk's "Verify" is blocked while any certificate on the application is
  more than six months past its issue date (check etls_certificates_valid);
- when the applicant submits or resubmits, a certificate that expires within
  30 days only gives a warning (check etls_certificates_expiring).

- etls.facility_letter_certificates.issued_on: required on the form from now
  on. Nullable here because applications from before this step have none;
  for them Verify says the date isn't recorded.
- core.transition_checks.warn_only: the check's findings are shown on the
  action (`warnings`) and recorded with the move, but never stop it.
"""
import sqlalchemy as sa
from alembic import op

revision = "0028"
down_revision = "0027"
branch_labels = None
depends_on = None

_FL_MOVES = """
    FROM core.workflow_transitions x
    JOIN core.workflows w ON w.id = x.workflow_id AND w.code = 'etls_facility_letter'
    JOIN core.workflow_statuses f ON f.id = x.from_status_id
    JOIN core.workflow_statuses t ON t.id = x.to_status_id
"""


def upgrade() -> None:
    op.add_column("facility_letter_certificates", sa.Column("issued_on", sa.Date), schema="etls")
    op.add_column(
        "transition_checks",
        sa.Column("warn_only", sa.Boolean, nullable=False, server_default=sa.false()),
        schema="core",
    )
    op.execute(
        f"""
        INSERT INTO core.transition_checks (transition_id, check_code)
        SELECT x.id, 'etls_certificates_valid' {_FL_MOVES}
        WHERE f.code = 'originals_received' AND t.code = 'verified'
        """
    )
    op.execute(
        f"""
        INSERT INTO core.transition_checks (transition_id, check_code, warn_only)
        SELECT x.id, 'etls_certificates_expiring', true {_FL_MOVES}
        WHERE f.code IN ('draft', 'returned') AND t.code = 'submitted'
        """
    )


def downgrade() -> None:
    op.execute(
        "DELETE FROM core.transition_checks WHERE check_code IN ('etls_certificates_valid', 'etls_certificates_expiring')"
    )
    op.drop_column("transition_checks", "warn_only", schema="core")
    op.drop_column("facility_letter_certificates", "issued_on", schema="etls")
