"""One signing flow for every facility letter; who may cancel; three copies of each letter.

Revision ID: 0041
Revises: 0040
Create Date: 2026-11-04

- Cement letters no longer have their own signers (the Minister or the PS).
  Every facility letter is signed by the Director, or by an authorised
  signatory while the Director is recorded absent. The cement rows added in
  0040 are deleted, and with them the two columns only they used
  (workflow_transitions.applies_when and own_post_only). The cement *receipt*
  is untouched: it's a document requirement (0020), not a signing rule.
- core.workflow_transitions.stand_in_must_be_issuer: someone acting for the
  post (delegation, succession, signatories list) may make the move only if
  they issued the case's current document. Set on "Cancel the signed
  letter": the Director, or the officer who signed that letter. [CONFIRM]
- core.issued_documents.signature_note: why the signer could sign, e.g. "in
  the Director's absence". Kept with the stored letter, though the printed
  letter no longer shows it (template version 4).
- etls.facility_letter_copies: signing stores one letter and records three
  copies of it: Records' file copy, GRA's (which Records dispatches from
  Outgoing, as before) and the applicant's (downloadable once GRA's is sent).
  Letters issued before this migration get their three copies too.
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0041"
down_revision = "0040"
branch_labels = None
depends_on = None

APP_ROLE = "motie_app"
CEMENT = '{"field": "hs_heading", "op": "equals", "value": "2523"}'
NOT_CEMENT = '{"field": "hs_heading", "op": "not_equals", "value": "2523"}'
RECIPIENTS = ("records_file", "gra", "applicant")

_FL_MOVES = """
    SELECT x.id FROM core.workflow_transitions x
    JOIN core.workflows w ON w.id = x.workflow_id AND w.code = 'etls_facility_letter'
"""

# The issued_documents guard (0022), now also keeping signature_note unchanged.
_GUARD = """
CREATE OR REPLACE FUNCTION core.issued_documents_guard() RETURNS trigger
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
        NEW.issued_by, NEW.issued_at, NEW.replaces_id{note_new})
       IS DISTINCT FROM
       (OLD.id, OLD.case_id, OLD.kind, OLD.filename, OLD.content_type, OLD.size_bytes,
        OLD.sha256, OLD.storage_key, OLD.template_version, OLD.template_sha256,
        OLD.issued_by, OLD.issued_at, OLD.replaces_id{note_old}) THEN
        RAISE EXCEPTION 'core.issued_documents: only a cancellation may be recorded';
    END IF;
    RETURN NEW;
END;
$$
"""


def upgrade() -> None:
    # --- Cement: back to the one flow --------------------------------------
    cement = f"{_FL_MOVES} WHERE x.applies_when->>'op' = 'equals'"
    op.execute(f"DELETE FROM core.transition_checks WHERE transition_id IN ({cement})")
    op.execute(f"DELETE FROM core.transition_effects WHERE transition_id IN ({cement})")
    op.execute(f"DELETE FROM core.workflow_transitions WHERE id IN ({cement})")
    op.drop_column("workflow_transitions", "own_post_only", schema="core")
    op.drop_constraint("workflow_transitions_applies_when_shape", "workflow_transitions", schema="core")
    op.drop_column("workflow_transitions", "applies_when", schema="core")

    # --- Who may cancel a signed letter -------------------------------------
    op.add_column(
        "workflow_transitions",
        sa.Column("stand_in_must_be_issuer", sa.Boolean, nullable=False, server_default=sa.false()),
        schema="core",
    )
    op.execute(
        f"""
        UPDATE core.workflow_transitions SET stand_in_must_be_issuer = true
        WHERE id IN ({_FL_MOVES} WHERE x.name = 'Cancel the signed letter')
        """
    )

    # --- Why the signer could sign, kept with the letter ----------------------
    op.add_column("issued_documents", sa.Column("signature_note", sa.Text, nullable=True), schema="core")
    op.execute(_GUARD.format(note_new=", NEW.signature_note", note_old=", OLD.signature_note"))
    # Letters signed under 0040 by a signatory: their signing audit row says why.
    op.execute(
        """
        UPDATE core.issued_documents d SET signature_note = e.details->>'in_absence'
        FROM core.audit_log i, core.audit_log e
        WHERE i.action = 'case.document_issued' AND (i.details->>'issued_document_id')::bigint = d.id
          AND e.entity_type = 'case' AND e.entity_id = i.entity_id AND e.action = 'case.status_changed'
          AND e.details->>'to' = 'signed' AND e.details->>'basis' = 'signatory'
          AND e.occurred_at = i.occurred_at
        """
    )

    # --- Three copies of each letter ------------------------------------------
    op.create_table(
        "facility_letter_copies",
        sa.Column("id", sa.BigInteger, sa.Identity(), primary_key=True),
        sa.Column("case_id", sa.BigInteger, sa.ForeignKey("etls.facility_letters.case_id"), nullable=False),
        sa.Column(
            "issued_document_id", sa.BigInteger, sa.ForeignKey("core.issued_documents.id"), nullable=False
        ),
        sa.Column("recipient", sa.Text, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint(f"recipient IN {RECIPIENTS!r}", name="facility_letter_copies_recipient"),
        sa.UniqueConstraint("issued_document_id", "recipient", name="facility_letter_copies_one_each"),
        schema="etls",
    )
    op.create_index("facility_letter_copies_case_idx", "facility_letter_copies", ["case_id"], schema="etls")
    op.execute(
        f"""
        INSERT INTO etls.facility_letter_copies (case_id, issued_document_id, recipient, created_at)
        SELECT d.case_id, d.id, r.recipient, d.issued_at
        FROM core.issued_documents d
        CROSS JOIN (VALUES {", ".join(f"('{r}')" for r in RECIPIENTS)}) AS r(recipient)
        WHERE d.kind = 'etls_facility_letter'
        """
    )
    # Written once, at signing; never changed or removed.
    op.execute(f"GRANT SELECT, INSERT ON etls.facility_letter_copies TO {APP_ROLE}")


def downgrade() -> None:
    op.drop_table("facility_letter_copies", schema="etls")
    op.execute(_GUARD.format(note_new="", note_old=""))
    op.drop_column("issued_documents", "signature_note", schema="core")
    op.drop_column("workflow_transitions", "stand_in_must_be_issuer", schema="core")

    # Back to 0040: the Director's rows apply to anything but cement, and the
    # Minister and the PS get cement-only copies of them, with their checks and effects.
    op.add_column("workflow_transitions", sa.Column("applies_when", JSONB, nullable=True), schema="core")
    op.create_check_constraint(
        "workflow_transitions_applies_when_shape",
        "workflow_transitions",
        "applies_when IS NULL OR ("
        "jsonb_typeof(applies_when) = 'object' "
        "AND applies_when ?& array['field', 'op', 'value'] "
        "AND applies_when->>'op' IN ('equals', 'not_equals', 'contains'))",
        schema="core",
    )
    op.add_column(
        "workflow_transitions",
        sa.Column("own_post_only", sa.Boolean, nullable=False, server_default=sa.false()),
        schema="core",
    )
    director = f"""{_FL_MOVES}
        JOIN core.positions p ON p.id = x.required_position_id AND p.code = 'director_of_industry'
        WHERE x.from_status_id IN (SELECT id FROM core.workflow_statuses WHERE code IN ('verified', 'signed', 'sent_to_gra'))
          AND x.name <> 'Mark sent to GRA'
    """
    columns = [
        "workflow_id", "from_status_id", "to_status_id", "by_applicant", "name", "requires_comment",
        "applicant_event", "applicant_visible", "requires_applicant_message", "allowed_on_hold", "is_correction",
    ]
    for position in ("permanent_secretary", "minister"):
        op.execute(
            f"""
            INSERT INTO core.workflow_transitions
                ({", ".join(columns)}, required_position_id, applies_when, own_post_only)
            SELECT {", ".join("x." + c for c in columns)}, p.id, '{CEMENT}'::jsonb, true
            FROM core.workflow_transitions x, core.positions p
            WHERE x.id IN ({director}) AND p.code = '{position}'
            """
        )
    for table, cols in (("transition_checks", ["check_code", "warn_only", "in_dry_run"]), ("transition_effects", ["effect_code"])):
        op.execute(
            f"""
            INSERT INTO core.{table} (transition_id, {", ".join(cols)})
            SELECT n.id, {", ".join("r." + c for c in cols)}
            FROM core.{table} r
            JOIN core.workflow_transitions o ON o.id = r.transition_id
            JOIN core.workflow_transitions n
              ON n.workflow_id = o.workflow_id AND n.from_status_id = o.from_status_id
             AND n.to_status_id = o.to_status_id AND n.applies_when IS NOT NULL
            WHERE o.id IN ({director})
            """
        )
    op.execute(f"UPDATE core.workflow_transitions SET applies_when = '{NOT_CEMENT}'::jsonb WHERE id IN ({director})")
