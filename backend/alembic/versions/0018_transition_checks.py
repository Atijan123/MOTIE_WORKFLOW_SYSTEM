"""Transition checks, and originals seen in person.

Revision ID: 0018
Revises: 0017
Create Date: 2026-10-19

A transition can carry named checks that must pass before the move is allowed.
The names are data (core.transition_checks); what each name checks is Python,
registered under that name (core/workflow/checks.py).

First use: Records may only confirm "originals received" on a facility letter
when every required document is uploaded *and* the original certificate of
origin has been marked as seen in person.
"""
import sqlalchemy as sa
from alembic import op

revision = "0018"
down_revision = "0017"
branch_labels = None
depends_on = None

APP_ROLE = "motie_app"


def upgrade() -> None:
    # Which documents must also be seen as paper originals, not just scanned.
    op.add_column(
        "document_requirements",
        sa.Column("original_required", sa.Boolean, nullable=False, server_default=sa.false()),
        schema="core",
    )
    op.add_column(
        "case_documents", sa.Column("original_seen_at", sa.DateTime(timezone=True), nullable=True), schema="core"
    )
    op.add_column(
        "case_documents",
        sa.Column("original_seen_by", sa.BigInteger, sa.ForeignKey("core.users.id"), nullable=True),
        schema="core",
    )
    op.create_check_constraint(
        "case_documents_original_seen_complete",
        "case_documents",
        "(original_seen_at IS NULL) = (original_seen_by IS NULL)",
        schema="core",
    )

    op.create_table(
        "transition_checks",
        sa.Column(
            "transition_id", sa.Integer, sa.ForeignKey("core.workflow_transitions.id"), primary_key=True
        ),
        sa.Column("check_code", sa.Text, primary_key=True),
        schema="core",
    )

    op.execute(
        """
        UPDATE core.document_requirements r SET original_required = true
        FROM core.workflows w, core.document_types t
        WHERE r.workflow_id = w.id AND w.code = 'etls_facility_letter'
          AND r.document_type_id = t.id AND t.code = 'certificate_of_origin'
        """
    )
    op.execute(
        """
        INSERT INTO core.transition_checks (transition_id, check_code)
        SELECT x.id, c.code
        FROM core.workflow_transitions x
        JOIN core.workflows w ON w.id = x.workflow_id AND w.code = 'etls_facility_letter'
        JOIN core.workflow_statuses f ON f.id = x.from_status_id AND f.code = 'submitted'
        JOIN core.workflow_statuses t ON t.id = x.to_status_id AND t.code = 'originals_received'
        CROSS JOIN (VALUES ('documents_complete'), ('originals_seen')) AS c(code)
        """
    )

    op.execute(f"GRANT SELECT ON core.transition_checks TO {APP_ROLE}")
    # Marking an original as seen fills in these two columns; nothing else about
    # an upload may change.
    op.execute(f"GRANT UPDATE (original_seen_at, original_seen_by) ON core.case_documents TO {APP_ROLE}")


def downgrade() -> None:
    op.drop_table("transition_checks", schema="core")
    op.execute(f"REVOKE UPDATE (original_seen_at, original_seen_by) ON core.case_documents FROM {APP_ROLE}")
    op.drop_constraint("case_documents_original_seen_complete", "case_documents", schema="core")
    op.drop_column("case_documents", "original_seen_by", schema="core")
    op.drop_column("case_documents", "original_seen_at", schema="core")
    op.drop_column("document_requirements", "original_required", schema="core")
