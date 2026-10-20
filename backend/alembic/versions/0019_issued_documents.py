"""Transition effects, and documents issued once and stored.

Revision ID: 0019
Revises: 0018
Create Date: 2026-10-20

A transition can now set off named effects in the same transaction as the move
(core.transition_effects; the code is registered in core/workflow/effects.py).

First use: when the PS (or someone acting for the PS) signs a facility letter,
the letter is rendered once and stored in core.issued_documents, with its
SHA-256 checksum and the template version. It is served from storage from then
on and never rendered again.
"""
import sqlalchemy as sa
from alembic import op

revision = "0019"
down_revision = "0018"
branch_labels = None
depends_on = None

APP_ROLE = "motie_app"


def upgrade() -> None:
    op.create_table(
        "transition_effects",
        sa.Column(
            "transition_id", sa.Integer, sa.ForeignKey("core.workflow_transitions.id"), primary_key=True
        ),
        sa.Column("effect_code", sa.Text, primary_key=True),
        schema="core",
    )
    op.create_table(
        "issued_documents",
        sa.Column("id", sa.BigInteger, sa.Identity(), primary_key=True),
        sa.Column("case_id", sa.BigInteger, sa.ForeignKey("core.cases.id"), nullable=False),
        sa.Column("kind", sa.Text, nullable=False),  # e.g. "etls_facility_letter"
        sa.Column("filename", sa.Text, nullable=False),
        sa.Column("content_type", sa.Text, nullable=False),
        sa.Column("size_bytes", sa.BigInteger, nullable=False),
        sa.Column("sha256", sa.Text, nullable=False),
        sa.Column("storage_key", sa.Text, nullable=False, unique=True),
        # Which wording it was made from: the label in the template file, and
        # the template file's own checksum (exact, even if nobody bumped the label).
        sa.Column("template_version", sa.Text, nullable=False),
        sa.Column("template_sha256", sa.Text, nullable=False),
        sa.Column("issued_by", sa.BigInteger, sa.ForeignKey("core.users.id"), nullable=False),
        sa.Column("issued_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        # Issued once: a second letter for the same case is refused.
        sa.UniqueConstraint("case_id", "kind", name="issued_documents_once_per_case"),
        sa.CheckConstraint("size_bytes > 0", name="issued_documents_not_empty"),
        schema="core",
    )

    op.execute(
        """
        INSERT INTO core.transition_effects (transition_id, effect_code)
        SELECT x.id, 'issue_facility_letter'
        FROM core.workflow_transitions x
        JOIN core.workflows w ON w.id = x.workflow_id AND w.code = 'etls_facility_letter'
        JOIN core.workflow_statuses f ON f.id = x.from_status_id AND f.code = 'verified'
        JOIN core.workflow_statuses t ON t.id = x.to_status_id AND t.code = 'signed'
        """
    )

    op.execute(f"GRANT SELECT ON core.transition_effects TO {APP_ROLE}")
    # Add only: an issued document is never edited or deleted by the app.
    op.execute(f"GRANT SELECT, INSERT ON core.issued_documents TO {APP_ROLE}")


def downgrade() -> None:
    op.drop_table("issued_documents", schema="core")
    op.drop_table("transition_effects", schema="core")
