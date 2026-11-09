"""Historical facility letters, imported from the Ministry's Excel register (step 11).

Revision ID: 0042
Revises: 0041
Create Date: 2026-11-05

Letters issued before this system, kept apart from live cases. They are not
cases and have no workflow: nobody moves, edits or signs them.

- etls.historical_letters: one row per letter (the sheet "Facility letters").
  Every column as written in the register, plus the scan file and page it
  came from, read from "PDF page(s)", and a date read from "Letter date" when
  it can be. A second paper copy of a letter is not a row: where it sits is
  the text in also_filed_at.
- etls.historical_goods_lines: the sheet "Goods lines", with the quantity read
  as a number when it can be.
- etls.historical_certificates: each certificate of origin number from a
  letter's "Certificate of origin no(s)." (split on ";"), normalised the way
  live numbers are, so the live duplicate check (S2) can search them.
- etls.historical_data_checks, and etls.historical_data_check_letters: the
  sheet "Data checks", as notes linked to the letters they mention.
- New role stats_viewer: may see the statistics page (S13), as may the Director.

The app's database user may only read these tables. The import command runs
as the schema owner (motie_owner) and replaces everything in one transaction.
"""
import sqlalchemy as sa
from alembic import op

revision = "0042"
down_revision = "0041"
branch_labels = None
depends_on = None

APP_ROLE = "motie_app"
TABLES = [
    "historical_data_check_letters",
    "historical_data_checks",
    "historical_certificates",
    "historical_goods_lines",
    "historical_letters",
]


def _text(*names: str) -> list[sa.Column]:
    """Columns kept exactly as written in the register (empty cell = NULL)."""
    return [sa.Column(n, sa.Text, nullable=True) for n in names]


def upgrade() -> None:
    op.execute("INSERT INTO core.roles (code, name) VALUES ('stats_viewer', 'Sees the ETLS statistics')")

    op.create_table(
        "historical_letters",
        sa.Column("id", sa.BigInteger, sa.Identity(), primary_key=True),
        sa.Column("letter_no", sa.Integer, nullable=False, unique=True),  # "Letter no."
        *_text(
            "folios",  # "Folio(s) in file"
            "pdf_pages",  # "PDF page(s)"
            "reference",  # "Letter reference"
            "letter_date_as_written",  # "Letter date"
            "importer",
            "importer_address",  # "Importer address / cc"
            "goods",  # "Goods (as in letter)"
            "category",
            "exporter",
            "exporter_country",
            "exporter_approval_as_written",  # "Exporter approval no. (as written)"
            "exporter_approval_standard",  # "Exporter approval no. (standard)"
            "product_approvals",  # "Product approval no(s)."
            "tariff_codes",  # "Tariff code(s)"
            "certificates_as_written",  # "Certificate of origin no(s)."
            "certificate_count_as_written",  # "No. of certificates"
            "bill_of_lading",  # "Bill of lading / container"
            "signed_by",
            "signed_as",
            "check_notes",
            "also_filed_at",  # "Also filed at (second copy of this letter)"
            "source_file",  # "File 2", from "PDF page(s)"
        ),
        # Read from letter_date_as_written; NULL when it can't be read.
        sa.Column("letter_date", sa.Date, nullable=True),
        sa.Column("source_page", sa.Integer, nullable=True),  # 7, from "PDF page(s)"
        sa.Column("source_row", sa.Integer, nullable=False),  # row in "Facility letters"
        sa.Column("imported_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        schema="etls",
    )
    op.create_index("historical_letters_date_idx", "historical_letters", ["letter_date"], schema="etls")

    op.create_table(
        "historical_goods_lines",
        sa.Column("id", sa.BigInteger, sa.Identity(), primary_key=True),
        sa.Column("letter_id", sa.BigInteger, sa.ForeignKey("etls.historical_letters.id"), nullable=False),
        *_text(
            "line_no_as_written",  # "Line no."
            "letter_no_as_written",
            "reference",
            "letter_date_as_written",
            "importer",
            "product",
            "category",
            "quantity_as_written",
            "unit",
            "exporter",
            "exporter_country",
        ),
        sa.Column("quantity", sa.Numeric(18, 3), nullable=True),  # read from quantity_as_written
        sa.Column("source_row", sa.Integer, nullable=False),
        schema="etls",
    )
    op.create_index("historical_goods_lines_letter_idx", "historical_goods_lines", ["letter_id"], schema="etls")

    op.create_table(
        "historical_certificates",
        sa.Column("id", sa.BigInteger, sa.Identity(), primary_key=True),
        sa.Column("letter_id", sa.BigInteger, sa.ForeignKey("etls.historical_letters.id"), nullable=False),
        sa.Column("number", sa.Text, nullable=False),  # as written
        sa.Column("number_normalized", sa.Text, nullable=False),  # as the live check compares
        schema="etls",
    )
    op.create_index(
        "historical_certificates_number_idx", "historical_certificates", ["number_normalized"], schema="etls"
    )
    op.create_index("historical_certificates_letter_idx", "historical_certificates", ["letter_id"], schema="etls")

    op.create_table(
        "historical_data_checks",
        sa.Column("id", sa.BigInteger, sa.Identity(), primary_key=True),
        *_text("check_no_as_written", "folios", "reference", "what_looks_wrong", "what_to_check"),
        sa.Column("source_row", sa.Integer, nullable=False),
        schema="etls",
    )
    op.create_table(
        "historical_data_check_letters",
        sa.Column("check_id", sa.BigInteger, sa.ForeignKey("etls.historical_data_checks.id"), primary_key=True),
        sa.Column("letter_id", sa.BigInteger, sa.ForeignKey("etls.historical_letters.id"), primary_key=True),
        schema="etls",
    )

    for table in TABLES:
        # Read-only for the API: only the import (as the owner) writes them.
        op.execute(f"GRANT SELECT ON etls.{table} TO {APP_ROLE}")


def downgrade() -> None:
    for table in TABLES:
        op.drop_table(table, schema="etls")
    # Fails if a user still has the role; take it away first rather than lose that silently.
    op.execute("DELETE FROM core.roles WHERE code = 'stats_viewer'")
