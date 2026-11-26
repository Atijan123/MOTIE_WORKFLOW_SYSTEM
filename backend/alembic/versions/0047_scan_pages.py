"""Pages of a document being scanned with a phone (step 13g).

Revision ID: 0047
Revises: 0046
Create Date: 2026-11-26

Records photographs a paper document page by page. Each page is checked,
turned upright, shrunk and stored as it arrives (one row here, its JPEG in
the documents folder); "Finish" joins them into one PDF, stored as an
ordinary upload, and deletes the pages. So nothing waits on the phone.

Pages are temporary: one set per person, case and document type. The app
may delete them (when finished, cancelled, or left for over a day).
"""
import sqlalchemy as sa
from alembic import op

revision = "0047"
down_revision = "0046"
branch_labels = None
depends_on = None

APP_ROLE = "motie_app"


def upgrade() -> None:
    op.create_table(
        "scan_pages",
        sa.Column("id", sa.BigInteger, sa.Identity(), primary_key=True),
        sa.Column("case_id", sa.BigInteger, sa.ForeignKey("core.cases.id"), nullable=False),
        sa.Column("document_type", sa.Text, nullable=False),
        sa.Column("user_id", sa.BigInteger, sa.ForeignKey("core.users.id"), nullable=False),
        sa.Column("page_no", sa.SmallInteger, nullable=False),
        sa.Column("storage_key", sa.Text, nullable=False, unique=True),
        sa.Column("size_bytes", sa.Integer, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("page_no > 0", name="scan_pages_page_no_positive"),
        sa.UniqueConstraint("case_id", "document_type", "user_id", "page_no", name="scan_pages_one_per_number"),
        schema="core",
    )
    op.execute(f"GRANT SELECT, INSERT, DELETE ON core.scan_pages TO {APP_ROLE}")
    op.execute(f"GRANT UPDATE (page_no, storage_key, size_bytes, created_at) ON core.scan_pages TO {APP_ROLE}")


def downgrade() -> None:
    op.drop_table("scan_pages", schema="core")
