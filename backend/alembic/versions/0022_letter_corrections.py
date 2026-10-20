"""Correcting a signed letter: cancel it with a reason, then sign a corrected one.

Revision ID: 0022
Revises: 0021
Create Date: 2026-10-20

- core.workflow_transitions.requires_comment: a move that needs a written
  reason (the comment) before the engine allows it.
- The PS (or someone acting for the PS) may "Cancel the signed letter", from
  "signed" or "sent_to_gra", back to "originals_received" [CONFIRM]. The desk
  can then correct what was wrong (e.g. the HS code) and verify again, and
  the PS signs a corrected letter. The move requires a reason.
- Its effect, cancel_facility_letter, marks the current letter cancelled
  (when, by whom, why). Both files stay stored; nothing is deleted.
- core.issued_documents: at most one *current* (not cancelled) document of a
  kind per case, instead of one ever. A trigger makes cancelling one-way and
  refuses any other change or a delete, even for the table owner.
"""
import sqlalchemy as sa
from alembic import op

revision = "0022"
down_revision = "0021"
branch_labels = None
depends_on = None

APP_ROLE = "motie_app"
CANCEL_FROM = ("signed", "sent_to_gra")


def upgrade() -> None:
    op.add_column(
        "workflow_transitions",
        sa.Column("requires_comment", sa.Boolean, nullable=False, server_default=sa.false()),
        schema="core",
    )

    op.add_column("issued_documents", sa.Column("cancelled_at", sa.DateTime(timezone=True)), schema="core")
    op.add_column(
        "issued_documents", sa.Column("cancelled_by", sa.BigInteger, sa.ForeignKey("core.users.id")), schema="core"
    )
    op.add_column("issued_documents", sa.Column("cancellation_reason", sa.Text), schema="core")
    # The corrected letter points at the one it replaces.
    op.add_column(
        "issued_documents",
        sa.Column("replaces_id", sa.BigInteger, sa.ForeignKey("core.issued_documents.id")),
        schema="core",
    )
    op.create_check_constraint(
        "issued_documents_cancellation_complete",
        "issued_documents",
        "(cancelled_at IS NULL) = (cancelled_by IS NULL) "
        "AND (cancelled_at IS NULL) = (cancellation_reason IS NULL) "
        "AND (cancellation_reason IS NULL OR btrim(cancellation_reason) <> '')",
        schema="core",
    )
    op.drop_constraint("issued_documents_once_per_case", "issued_documents", schema="core")
    op.create_index(
        "issued_documents_one_current",
        "issued_documents",
        ["case_id", "kind"],
        unique=True,
        schema="core",
        postgresql_where=sa.text("cancelled_at IS NULL"),
    )

    # Like the audit log's triggers (0003): the database itself refuses, so no
    # client, not even the owner, can un-cancel a letter, edit one or delete one.
    op.execute(
        """
        CREATE FUNCTION core.issued_documents_guard() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'core.issued_documents: issued documents are never deleted';
            END IF;
            IF OLD.cancelled_at IS NOT NULL THEN
                RAISE EXCEPTION 'core.issued_documents: a cancelled document can''t be changed';
            END IF;
            IF (NEW.id, NEW.case_id, NEW.kind, NEW.filename, NEW.content_type, NEW.size_bytes,
                NEW.sha256, NEW.storage_key, NEW.template_version, NEW.template_sha256,
                NEW.issued_by, NEW.issued_at, NEW.replaces_id)
               IS DISTINCT FROM
               (OLD.id, OLD.case_id, OLD.kind, OLD.filename, OLD.content_type, OLD.size_bytes,
                OLD.sha256, OLD.storage_key, OLD.template_version, OLD.template_sha256,
                OLD.issued_by, OLD.issued_at, OLD.replaces_id) THEN
                RAISE EXCEPTION 'core.issued_documents: only a cancellation may be recorded';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        "CREATE TRIGGER issued_documents_guard BEFORE UPDATE OR DELETE ON core.issued_documents "
        "FOR EACH ROW EXECUTE FUNCTION core.issued_documents_guard()"
    )

    op.execute(
        f"""
        INSERT INTO core.workflow_transitions
            (workflow_id, from_status_id, to_status_id, required_position_id, name, requires_comment)
        SELECT w.id, f.id, t.id, p.id, 'Cancel the signed letter', true
        FROM core.workflows w
        JOIN core.workflow_statuses f ON f.workflow_id = w.id AND f.code IN {CANCEL_FROM!r}
        JOIN core.workflow_statuses t ON t.workflow_id = w.id AND t.code = 'originals_received'
        JOIN core.positions p ON p.code = 'permanent_secretary'
        WHERE w.code = 'etls_facility_letter'
        """
    )
    op.execute(
        f"""
        INSERT INTO core.transition_effects (transition_id, effect_code)
        SELECT x.id, 'cancel_facility_letter'
        FROM core.workflow_transitions x
        JOIN core.workflows w ON w.id = x.workflow_id AND w.code = 'etls_facility_letter'
        JOIN core.workflow_statuses f ON f.id = x.from_status_id AND f.code IN {CANCEL_FROM!r}
        JOIN core.workflow_statuses t ON t.id = x.to_status_id AND t.code = 'originals_received'
        """
    )

    op.execute(
        f"GRANT UPDATE (cancelled_at, cancelled_by, cancellation_reason) ON core.issued_documents TO {APP_ROLE}"
    )


def downgrade() -> None:
    conn = op.get_bind()
    if conn.execute(sa.text("SELECT count(*) FROM core.issued_documents WHERE cancelled_at IS NOT NULL")).scalar():
        # Going back would mean forgetting cancellations or deleting letters.
        raise RuntimeError("Can't downgrade 0022: some issued documents have been cancelled.")
    op.execute(
        f"REVOKE UPDATE (cancelled_at, cancelled_by, cancellation_reason) ON core.issued_documents FROM {APP_ROLE}"
    )
    # One statement per execute(): asyncpg refuses several in one.
    op.execute("DELETE FROM core.transition_effects WHERE effect_code = 'cancel_facility_letter'")
    op.execute(
        """
        DELETE FROM core.workflow_transitions x USING core.workflows w
        WHERE x.workflow_id = w.id AND w.code = 'etls_facility_letter'
          AND x.name = 'Cancel the signed letter'
        """
    )
    op.execute("DROP TRIGGER issued_documents_guard ON core.issued_documents")
    op.execute("DROP FUNCTION core.issued_documents_guard()")
    op.drop_index("issued_documents_one_current", "issued_documents", schema="core")
    op.create_unique_constraint(
        "issued_documents_once_per_case", "issued_documents", ["case_id", "kind"], schema="core"
    )
    op.drop_constraint("issued_documents_cancellation_complete", "issued_documents", schema="core")
    for column in ("replaces_id", "cancellation_reason", "cancelled_by", "cancelled_at"):
        op.drop_column("issued_documents", column, schema="core")
    op.drop_column("workflow_transitions", "requires_comment", schema="core")
