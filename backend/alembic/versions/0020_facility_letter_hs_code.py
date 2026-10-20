"""HS code on facility letters, confirmed by an officer; the receipt rule uses it.

Revision ID: 0020
Revises: 0019
Create Date: 2026-10-20

Replaces the placeholder "product contains 'cement'" rule (0017) with the HS
heading: the receipt is required when the HS code starts with 2523 (Portland
cement, aluminous cement, slag cement and similar) [CONFIRM].

- The applicant declares an HS code on the form (hs_code).
- An officer confirms it, or corrects it (hs_code_confirmed, by, at), during
  the desk's verification. The desk's "Verify" move now needs that, and needs
  the documents to be complete for the *confirmed* code.
- The rule is still a row in core.document_requirements:
      {"field": "hs_heading", "op": "equals", "value": "2523"}
"""
import sqlalchemy as sa
from alembic import op

revision = "0020"
down_revision = "0019"
branch_labels = None
depends_on = None

APP_ROLE = "motie_app"
# Digits only (dots and spaces are removed before saving): 6 for the
# international HS code, 8 or 10 for national/ECOWAS tariff lines.
HS_CODE_SHAPE = "^[0-9]{6}([0-9]{2}){0,2}$"

OLD_CONDITION = '{"field": "product", "op": "contains", "value": "cement"}'
NEW_CONDITION = '{"field": "hs_heading", "op": "equals", "value": "2523"}'


def _set_receipt_condition(condition: str) -> None:
    op.execute(
        f"""
        UPDATE core.document_requirements r SET condition = '{condition}'::jsonb
        FROM core.workflows w, core.document_types t
        WHERE r.workflow_id = w.id AND w.code = 'etls_facility_letter'
          AND r.document_type_id = t.id AND t.code = 'cement_receipt'
        """
    )


_VERIFY_MOVE = """
    FROM core.workflow_transitions x
    JOIN core.workflows w ON w.id = x.workflow_id AND w.code = 'etls_facility_letter'
    JOIN core.workflow_statuses f ON f.id = x.from_status_id AND f.code = 'originals_received'
    JOIN core.workflow_statuses t ON t.id = x.to_status_id AND t.code = 'verified'
"""
VERIFY_CHECKS = ("documents_complete", "hs_code_confirmed")


def upgrade() -> None:
    # Nullable: cases submitted before this step have no HS code. New forms
    # must give one (schemas.py).
    op.add_column("facility_letters", sa.Column("hs_code", sa.Text, nullable=True), schema="etls")
    op.add_column("facility_letters", sa.Column("hs_code_confirmed", sa.Text, nullable=True), schema="etls")
    op.add_column(
        "facility_letters",
        sa.Column("hs_code_confirmed_by", sa.BigInteger, sa.ForeignKey("core.users.id"), nullable=True),
        schema="etls",
    )
    op.add_column(
        "facility_letters",
        sa.Column("hs_code_confirmed_at", sa.DateTime(timezone=True), nullable=True),
        schema="etls",
    )
    op.create_check_constraint(
        "facility_letters_hs_code_shape", "facility_letters", f"hs_code ~ '{HS_CODE_SHAPE}'", schema="etls"
    )
    op.create_check_constraint(
        "facility_letters_hs_code_confirmed_shape",
        "facility_letters",
        f"hs_code_confirmed ~ '{HS_CODE_SHAPE}'",
        schema="etls",
    )
    # A confirmed code always says who confirmed it and when.
    op.create_check_constraint(
        "facility_letters_hs_code_confirmed_complete",
        "facility_letters",
        "(hs_code_confirmed IS NULL) = (hs_code_confirmed_by IS NULL) "
        "AND (hs_code_confirmed IS NULL) = (hs_code_confirmed_at IS NULL)",
        schema="etls",
    )

    _set_receipt_condition(NEW_CONDITION)
    op.execute(
        "INSERT INTO core.transition_checks (transition_id, check_code) "
        f"SELECT x.id, c.code {_VERIFY_MOVE} "
        f"CROSS JOIN (VALUES {', '.join(f'({c!r})' for c in VERIFY_CHECKS)}) AS c(code)"
    )

    # Confirming fills in these three columns; nothing else on the form may change.
    op.execute(
        "GRANT UPDATE (hs_code_confirmed, hs_code_confirmed_by, hs_code_confirmed_at) "
        f"ON etls.facility_letters TO {APP_ROLE}"
    )


def downgrade() -> None:
    op.execute(
        "REVOKE UPDATE (hs_code_confirmed, hs_code_confirmed_by, hs_code_confirmed_at) "
        f"ON etls.facility_letters FROM {APP_ROLE}"
    )
    op.execute(
        "DELETE FROM core.transition_checks c USING core.workflow_transitions x "
        "JOIN core.workflows w ON w.id = x.workflow_id AND w.code = 'etls_facility_letter' "
        "JOIN core.workflow_statuses f ON f.id = x.from_status_id AND f.code = 'originals_received' "
        "JOIN core.workflow_statuses t ON t.id = x.to_status_id AND t.code = 'verified' "
        f"WHERE c.transition_id = x.id AND c.check_code IN {VERIFY_CHECKS!r}"
    )
    _set_receipt_condition(OLD_CONDITION)
    for column in ("hs_code_confirmed_at", "hs_code_confirmed_by", "hs_code_confirmed", "hs_code"):
        op.drop_column("facility_letters", column, schema="etls")
