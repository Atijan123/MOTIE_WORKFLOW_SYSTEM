"""Drafts: applications start as an editable draft, and the applicant submits.

Revision ID: 0026
Revises: 0025
Create Date: 2026-10-24

- core.workflow_transitions.by_applicant: a move the case's applicant makes
  (e.g. "Submit"), not a Ministry post. Such a move names no post, so
  required_position_id becomes nullable; a check keeps the two in step.
- core.workflow_statuses.applicant_editable: in this status the applicant may
  still change the form (a draft; later also "returned").
- Facility letters: a new initial status "draft", and the applicant's move
  "Submit" (draft -> submitted). Submit needs every document known to be
  needed (the same lenient check as Records), and has two effects:
  assign_reference (the case reference is given at submission, 0024) and
  etls_check_duplicate_certificates (moved here from opening the case, so a
  draft's numbers don't count as used).
- The app may now edit the form (UPDATE on etls.facility_letters, DELETE on
  its two child tables, whose rows are replaced on each save). The service
  allows it only while the status is applicant_editable.
"""
import sqlalchemy as sa
from alembic import op

revision = "0026"
down_revision = "0025"
branch_labels = None
depends_on = None

APP_ROLE = "motie_app"

FORM_COLUMNS = (
    "importer_name, importer_address, product, quantity, unit, exporter_name, "
    "exporter_country, exporter_etls_approval_number, hs_code"
)

_SUBMIT_MOVE = """
    FROM core.workflow_transitions x
    JOIN core.workflows w ON w.id = x.workflow_id AND w.code = 'etls_facility_letter'
    JOIN core.workflow_statuses f ON f.id = x.from_status_id AND f.code = 'draft'
"""


def upgrade() -> None:
    op.add_column(
        "workflow_transitions",
        sa.Column("by_applicant", sa.Boolean, nullable=False, server_default=sa.false()),
        schema="core",
    )
    op.alter_column("workflow_transitions", "required_position_id", nullable=True, schema="core")
    # Every move belongs to exactly one of: a post, or the applicant.
    op.create_check_constraint(
        "workflow_transitions_post_or_applicant",
        "workflow_transitions",
        "by_applicant = (required_position_id IS NULL)",
        schema="core",
    )
    op.add_column(
        "workflow_statuses",
        sa.Column("applicant_editable", sa.Boolean, nullable=False, server_default=sa.false()),
        schema="core",
    )

    # One initial status per workflow (a unique index), so "submitted" stops
    # being initial before "draft" is added.
    op.execute(
        """
        UPDATE core.workflow_statuses s SET is_initial = false
        FROM core.workflows w
        WHERE s.workflow_id = w.id AND w.code = 'etls_facility_letter' AND s.code = 'submitted'
        """
    )
    op.execute(
        """
        INSERT INTO core.workflow_statuses
            (workflow_id, code, name, is_initial, applicant_editable, applicant_label, applicant_explanation)
        SELECT w.id, 'draft', 'Draft (not submitted)', true, true, 'Draft',
               'Not sent yet. Upload your documents, then submit.'
        FROM core.workflows w WHERE w.code = 'etls_facility_letter'
        """
    )
    op.execute(
        """
        INSERT INTO core.workflow_transitions
            (workflow_id, from_status_id, to_status_id, required_position_id, by_applicant, name)
        SELECT w.id, f.id, t.id, NULL, true, 'Submit'
        FROM core.workflows w
        JOIN core.workflow_statuses f ON f.workflow_id = w.id AND f.code = 'draft'
        JOIN core.workflow_statuses t ON t.workflow_id = w.id AND t.code = 'submitted'
        WHERE w.code = 'etls_facility_letter'
        """
    )
    op.execute(
        f"""
        INSERT INTO core.transition_checks (transition_id, check_code)
        SELECT x.id, 'known_documents_complete' {_SUBMIT_MOVE}
        """
    )
    op.execute(
        f"""
        INSERT INTO core.transition_effects (transition_id, effect_code)
        SELECT x.id, e.code {_SUBMIT_MOVE}
        CROSS JOIN (VALUES ('assign_reference'), ('etls_check_duplicate_certificates')) AS e(code)
        """
    )

    op.execute(f"GRANT UPDATE ({FORM_COLUMNS}) ON etls.facility_letters TO {APP_ROLE}")
    op.execute(
        f"GRANT DELETE ON etls.facility_letter_product_approvals, etls.facility_letter_certificates TO {APP_ROLE}"
    )


def downgrade() -> None:
    conn = op.get_bind()
    in_draft = conn.execute(
        sa.text(
            "SELECT count(*) FROM core.cases c JOIN core.workflow_statuses s ON s.id = c.current_status_id "
            "WHERE s.code = 'draft'"
        )
    ).scalar()
    if in_draft:
        # Their status would disappear; they'd have nowhere to be.
        raise RuntimeError("Can't downgrade 0026: some cases are drafts.")

    op.execute(
        f"REVOKE DELETE ON etls.facility_letter_product_approvals, etls.facility_letter_certificates FROM {APP_ROLE}"
    )
    op.execute(f"REVOKE UPDATE ({FORM_COLUMNS}) ON etls.facility_letters FROM {APP_ROLE}")
    # One statement per execute(): asyncpg refuses several in one.
    for table in ("transition_effects", "transition_checks"):
        op.execute(f"DELETE FROM core.{table} WHERE transition_id IN (SELECT x.id {_SUBMIT_MOVE})")
    op.execute(f"DELETE FROM core.workflow_transitions WHERE id IN (SELECT x.id {_SUBMIT_MOVE})")
    op.execute(
        """
        DELETE FROM core.workflow_statuses s USING core.workflows w
        WHERE s.workflow_id = w.id AND w.code = 'etls_facility_letter' AND s.code = 'draft'
        """
    )
    op.execute(
        """
        UPDATE core.workflow_statuses s SET is_initial = true
        FROM core.workflows w
        WHERE s.workflow_id = w.id AND w.code = 'etls_facility_letter' AND s.code = 'submitted'
        """
    )
    op.drop_column("workflow_statuses", "applicant_editable", schema="core")
    op.drop_constraint("workflow_transitions_post_or_applicant", "workflow_transitions", schema="core")
    op.alter_column("workflow_transitions", "required_position_id", nullable=False, schema="core")
    op.drop_column("workflow_transitions", "by_applicant", schema="core")
