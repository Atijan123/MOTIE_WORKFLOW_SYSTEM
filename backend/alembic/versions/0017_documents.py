"""Documents: types, per-workflow requirements (optionally conditional), and uploads.

Revision ID: 0017
Revises: 0016
Create Date: 2026-10-19

Which documents a workflow needs is data. A requirement can have a condition,
tested against facts the module supplies about the case (e.g. the product):

    {"field": "product", "op": "contains", "value": "cement"}

so "a receipt when the product is cement" is a row, not code. The file itself is
stored on disk (DOCUMENT_STORAGE_DIR); the table keeps its details and checksum.
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0017"
down_revision = "0016"
branch_labels = None
depends_on = None

APP_ROLE = "motie_app"


def upgrade() -> None:
    op.create_table(
        "document_types",
        sa.Column("id", sa.SmallInteger, sa.Identity(), primary_key=True),
        sa.Column("code", sa.Text, nullable=False, unique=True),
        sa.Column("name", sa.Text, nullable=False),
        schema="core",
    )
    op.create_table(
        "document_requirements",
        sa.Column("id", sa.SmallInteger, sa.Identity(), primary_key=True),
        sa.Column("workflow_id", sa.SmallInteger, sa.ForeignKey("core.workflows.id"), nullable=False),
        sa.Column(
            "document_type_id", sa.SmallInteger, sa.ForeignKey("core.document_types.id"), nullable=False
        ),
        # Empty = always required. Otherwise required only when the condition holds.
        sa.Column("condition", JSONB, nullable=True),
        sa.UniqueConstraint("workflow_id", "document_type_id", name="document_requirements_key"),
        # Only the small condition language documents/conditions.py understands.
        # Anything else is refused here, so a typo can't silently switch a rule off.
        sa.CheckConstraint(
            "condition IS NULL OR ("
            "jsonb_typeof(condition) = 'object' "
            "AND condition ?& array['field', 'op', 'value'] "
            "AND condition->>'op' IN ('equals', 'contains'))",
            name="document_requirements_condition_shape",
        ),
        schema="core",
    )
    op.create_table(
        "case_documents",
        sa.Column("id", sa.BigInteger, sa.Identity(), primary_key=True),
        sa.Column("case_id", sa.BigInteger, sa.ForeignKey("core.cases.id"), nullable=False),
        sa.Column(
            "document_type_id", sa.SmallInteger, sa.ForeignKey("core.document_types.id"), nullable=False
        ),
        sa.Column("filename", sa.Text, nullable=False),  # cleaned-up name, for display only
        sa.Column("content_type", sa.Text, nullable=False),  # detected from the file, not the client
        sa.Column("size_bytes", sa.BigInteger, nullable=False),
        sa.Column("sha256", sa.Text, nullable=False),  # proves later the file wasn't changed
        # Random name on disk. User input never becomes part of a path.
        sa.Column("storage_key", sa.Text, nullable=False, unique=True),
        sa.Column("uploaded_by", sa.BigInteger, sa.ForeignKey("core.users.id"), nullable=False),
        sa.Column(
            "uploaded_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint("size_bytes > 0", name="case_documents_not_empty"),
        schema="core",
    )
    op.create_index("case_documents_case_idx", "case_documents", ["case_id"], schema="core")

    # [CONFIRM] Names of the document types, and which receipt cement imports need.
    op.execute(
        """
        INSERT INTO core.document_types (code, name) VALUES
            ('business_registration',      'Business registration certificate'),
            ('annual_returns_certificate', 'Annual returns certificate'),
            ('certificate_of_origin',      'Certificate of origin'),
            ('invoice',                    'Invoice'),
            ('export_declaration',         'Export declaration'),
            ('cement_receipt',             'Receipt (cement imports)')
        """
    )
    # [CONFIRM] "contains 'cement'" in the free-text product is a stand-in for a
    # proper product category. It would also match e.g. "cement mixer".
    op.execute(
        """
        INSERT INTO core.document_requirements (workflow_id, document_type_id, condition)
        SELECT w.id, t.id, r.condition::jsonb
        FROM (VALUES
            ('business_registration',      NULL),
            ('annual_returns_certificate', NULL),
            ('certificate_of_origin',      NULL),
            ('invoice',                    NULL),
            ('export_declaration',         NULL),
            ('cement_receipt',             '{"field": "product", "op": "contains", "value": "cement"}')
        ) AS r(type_code, condition)
        JOIN core.document_types t ON t.code = r.type_code
        JOIN core.workflows w ON w.code = 'etls_facility_letter'
        """
    )

    op.execute(f"GRANT SELECT ON core.document_types, core.document_requirements TO {APP_ROLE}")
    # Uploads are kept: a new version is a new row; nothing is edited or deleted.
    op.execute(f"GRANT SELECT, INSERT ON core.case_documents TO {APP_ROLE}")


def downgrade() -> None:
    op.drop_table("case_documents", schema="core")
    op.drop_table("document_requirements", schema="core")
    op.drop_table("document_types", schema="core")
