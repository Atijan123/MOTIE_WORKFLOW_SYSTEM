"""Authorised signatories sign in the Director's absence; cement letters need the Minister or the PS.

Revision ID: 0040
Revises: 0039
Create Date: 2026-11-04

The rule for signing in the Director's absence changed (SCREENS.md S12, S3, S5):

- core.signatory_lists: a named list of people (not posts). One list for now,
  "director_absence", kept by the Director's office.
- core.authorised_signatories: who is on a list, with when and by whom they
  were added and removed. A removal is one-way: someone put back on the list
  gets a new row, so the record of who could sign when is never rewritten.
- core.signatory_rules: per workflow, "while every holder of <post> is
  recorded absent, the people on <list> may make its moves, instead of the
  succession order". Both the facility letter and the ETLS approval point at
  the same list today; splitting them later is a new list and an UPDATE.
- The succession row "DPS Admin & Finance acts for the Director (ETLS)" is
  removed: the list replaces it.
- New role signatory_admin (the Director's office) keeps the lists (S12).

The facility letter is now signed by the Director of Industry and Investment
(S3), except cement (HS heading 2523, as the desk confirms it), which only the
Minister or the PS may sign:

- core.workflow_transitions.applies_when: a condition in the documents'
  condition language ({"field", "op", "value"}) tested against the module's
  facts. A move whose condition doesn't hold isn't offered at all (it's not
  "blocked": it isn't that case's move). Empty = always.
- core.workflow_transitions.own_post_only: only holders of the post itself
  may make the move: no delegation, no succession, no signatory list.
- Each of the PS's facility letter moves (sign, return to the desk, cancel the
  signed letter) becomes three rows: the Director's (not cement), and the
  Minister's and the PS's (cement, own post only). Each copy keeps the
  original's checks and effects.
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0040"
down_revision = "0039"
branch_labels = None
depends_on = None

APP_ROLE = "motie_app"
LIST = "director_absence"
CEMENT = '{"field": "hs_heading", "op": "equals", "value": "2523"}'
NOT_CEMENT = '{"field": "hs_heading", "op": "not_equals", "value": "2523"}'

# The PS's moves on the facility letter: they all belong to whoever signs.
_PS_MOVES = """
    SELECT x.id FROM core.workflow_transitions x
    JOIN core.workflows w ON w.id = x.workflow_id AND w.code = 'etls_facility_letter'
    JOIN core.positions p ON p.id = x.required_position_id AND p.code = 'permanent_secretary'
"""
# Everything about a move except its post and the two new columns.
_COPY_COLUMNS = [
    "workflow_id", "from_status_id", "to_status_id", "by_applicant", "name", "requires_comment",
    "applicant_event", "applicant_visible", "requires_applicant_message", "allowed_on_hold", "is_correction",
]


def _copy_rows(table: str, columns: list[str]) -> None:
    """Copy the PS moves' rows in core.<table> to their new copies. A copy is
    the move with the same workflow, from and to, and another post."""
    op.execute(
        f"""
        INSERT INTO core.{table} (transition_id, {", ".join(columns)})
        SELECT n.id, {", ".join("r." + c for c in columns)}
        FROM core.{table} r
        JOIN core.workflow_transitions o ON o.id = r.transition_id
        JOIN core.workflow_transitions n
          ON n.workflow_id = o.workflow_id AND n.from_status_id = o.from_status_id
         AND n.to_status_id = o.to_status_id AND n.id <> o.id
        WHERE o.id IN ({_PS_MOVES})
        """
    )


def upgrade() -> None:
    op.execute(
        "INSERT INTO core.roles (code, name) VALUES ('signatory_admin', 'Keeps the authorised signatories lists')"
    )

    op.create_table(
        "signatory_lists",
        sa.Column("id", sa.SmallInteger, sa.Identity(), primary_key=True),
        sa.Column("code", sa.Text, nullable=False, unique=True),
        sa.Column("name", sa.Text, nullable=False),
        # How the letter and the history say why this person signed.
        sa.Column("absence_wording", sa.Text, nullable=False),
        schema="core",
    )
    op.create_table(
        "authorised_signatories",
        sa.Column("id", sa.BigInteger, sa.Identity(), primary_key=True),
        sa.Column("list_id", sa.SmallInteger, sa.ForeignKey("core.signatory_lists.id"), nullable=False),
        sa.Column("user_id", sa.BigInteger, sa.ForeignKey("core.users.id"), nullable=False),
        sa.Column("added_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("added_by", sa.BigInteger, sa.ForeignKey("core.users.id"), nullable=False),
        sa.Column("removed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("removed_by", sa.BigInteger, sa.ForeignKey("core.users.id"), nullable=True),
        sa.CheckConstraint(
            "(removed_at IS NULL) = (removed_by IS NULL)", name="authorised_signatories_removed_complete"
        ),
        schema="core",
    )
    # Someone is on a list at most once at a time (a past row doesn't count).
    op.create_index(
        "authorised_signatories_current_key",
        "authorised_signatories",
        ["list_id", "user_id"],
        unique=True,
        schema="core",
        postgresql_where=sa.text("removed_at IS NULL"),
    )
    # Like issued_documents (0022): the database itself refuses to undo a
    # removal or change who was added, by whom and when.
    op.execute(
        """
        CREATE FUNCTION core.authorised_signatories_guard() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'core.authorised_signatories: rows are never deleted';
            END IF;
            IF OLD.removed_at IS NOT NULL THEN
                RAISE EXCEPTION 'core.authorised_signatories: a removal can''t be changed';
            END IF;
            IF (NEW.id, NEW.list_id, NEW.user_id, NEW.added_at, NEW.added_by)
               IS DISTINCT FROM (OLD.id, OLD.list_id, OLD.user_id, OLD.added_at, OLD.added_by) THEN
                RAISE EXCEPTION 'core.authorised_signatories: only a removal may be recorded';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        "CREATE TRIGGER authorised_signatories_guard BEFORE UPDATE OR DELETE ON core.authorised_signatories "
        "FOR EACH ROW EXECUTE FUNCTION core.authorised_signatories_guard()"
    )
    op.create_table(
        "signatory_rules",
        sa.Column("workflow_id", sa.SmallInteger, sa.ForeignKey("core.workflows.id"), primary_key=True),
        sa.Column("position_id", sa.SmallInteger, sa.ForeignKey("core.positions.id"), primary_key=True),
        sa.Column("list_id", sa.SmallInteger, sa.ForeignKey("core.signatory_lists.id"), nullable=False),
        schema="core",
    )

    op.execute(
        f"""
        INSERT INTO core.signatory_lists (code, name, absence_wording)
        VALUES ('{LIST}', 'Authorised signatories in the Director''s absence', 'in the Director''s absence')
        """
    )
    # [CONFIRM] One list for both. etls_application is the ETLS approval
    # workflow until etls_approval replaces it; that migration adds its own row.
    op.execute(
        f"""
        INSERT INTO core.signatory_rules (workflow_id, position_id, list_id)
        SELECT w.id, p.id, l.id
        FROM core.workflows w, core.positions p, core.signatory_lists l
        WHERE w.code IN ('etls_facility_letter', 'etls_application')
          AND p.code = 'director_of_industry' AND l.code = '{LIST}'
        """
    )
    op.execute(
        """
        DELETE FROM core.succession_orders s
        USING core.positions p, core.workflows w
        WHERE s.position_id = p.id AND p.code = 'director_of_industry'
          AND s.workflow_id = w.id AND w.code = 'etls_application'
        """
    )

    op.add_column("workflow_transitions", sa.Column("applies_when", JSONB, nullable=True), schema="core")
    op.create_check_constraint(
        "workflow_transitions_applies_when_shape",
        "workflow_transitions",
        # The documents' condition language (core/documents/conditions.py).
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

    # The facility letter: the Director signs, the Minister or the PS for cement.
    for position, condition, own_only in (
        ("director_of_industry", NOT_CEMENT, "false"),
        ("minister", CEMENT, "true"),
    ):
        op.execute(
            f"""
            INSERT INTO core.workflow_transitions
                ({", ".join(_COPY_COLUMNS)}, required_position_id, applies_when, own_post_only)
            SELECT {", ".join("x." + c for c in _COPY_COLUMNS)}, p.id, '{condition}'::jsonb, {own_only}
            FROM core.workflow_transitions x, core.positions p
            WHERE x.id IN ({_PS_MOVES}) AND p.code = '{position}'
            """
        )
    # Each copy gets the PS row's checks and effects (e.g. "issue the letter").
    _copy_rows("transition_checks", ["check_code", "warn_only", "in_dry_run"])
    _copy_rows("transition_effects", ["effect_code"])
    op.execute(
        f"UPDATE core.workflow_transitions SET applies_when = '{CEMENT}'::jsonb, own_post_only = true "
        f"WHERE id IN ({_PS_MOVES})"
    )
    op.execute(
        """
        UPDATE core.workflow_statuses s SET name = 'Letter signed'
        FROM core.workflows w
        WHERE s.workflow_id = w.id AND w.code = 'etls_facility_letter' AND s.code = 'signed'
        """
    )

    op.execute(f"GRANT SELECT ON core.signatory_lists, core.signatory_rules TO {APP_ROLE}")
    op.execute(f"GRANT SELECT, INSERT ON core.authorised_signatories TO {APP_ROLE}")
    op.execute(f"GRANT UPDATE (removed_at, removed_by) ON core.authorised_signatories TO {APP_ROLE}")


def downgrade() -> None:
    conn = op.get_bind()
    if conn.execute(sa.text("SELECT count(*) FROM core.authorised_signatories")).scalar():
        # Going back would forget who could sign when.
        raise RuntimeError("Can't downgrade 0040: the signatories lists have entries.")
    op.execute(
        """
        UPDATE core.workflow_statuses s SET name = 'Signed by the PS'
        FROM core.workflows w
        WHERE s.workflow_id = w.id AND w.code = 'etls_facility_letter' AND s.code = 'signed'
        """
    )
    _copies = """
        SELECT x.id FROM core.workflow_transitions x
        JOIN core.workflows w ON w.id = x.workflow_id AND w.code = 'etls_facility_letter'
        JOIN core.positions p ON p.id = x.required_position_id
        WHERE p.code IN ('director_of_industry', 'minister') AND x.applies_when IS NOT NULL
    """
    op.execute(f"DELETE FROM core.transition_checks WHERE transition_id IN ({_copies})")
    op.execute(f"DELETE FROM core.transition_effects WHERE transition_id IN ({_copies})")
    op.execute(f"DELETE FROM core.workflow_transitions WHERE id IN ({_copies})")
    op.drop_column("workflow_transitions", "own_post_only", schema="core")
    op.drop_constraint("workflow_transitions_applies_when_shape", "workflow_transitions", schema="core")
    op.drop_column("workflow_transitions", "applies_when", schema="core")

    op.execute(
        """
        INSERT INTO core.succession_orders (position_id, workflow_id, rank, successor_position_id)
        SELECT p.id, w.id, 1, n.id
        FROM core.positions p, core.workflows w, core.positions n
        WHERE p.code = 'director_of_industry' AND w.code = 'etls_application' AND n.code = 'dps_admin_finance'
        """
    )
    op.drop_table("signatory_rules", schema="core")
    op.execute("DROP TRIGGER authorised_signatories_guard ON core.authorised_signatories")
    op.execute("DROP FUNCTION core.authorised_signatories_guard()")
    op.drop_table("authorised_signatories", schema="core")
    op.drop_table("signatory_lists", schema="core")
    # Fails if a user still has the role; take it away first rather than lose that silently.
    op.execute("DELETE FROM core.roles WHERE code = 'signatory_admin'")
