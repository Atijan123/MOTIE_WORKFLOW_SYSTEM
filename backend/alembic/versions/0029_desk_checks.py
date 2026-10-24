"""Desk checks: recorded ticks, and rejecting while a case is on hold.

Revision ID: 0029
Revises: 0028
Create Date: 2026-10-24

- core.checklist_items: things an officer must tick at a step, per workflow,
  e.g. "the exporter's approval is on the ECOWAS ETLS list". Data, like the
  rest of the workflow.
- core.case_ticks: who ticked which item on which case, and when. Unticking
  deletes the row; both are in the audit log.
- Check checklist_complete: every item for the case's current step is ticked.
  On the desk's Verify.
- Effect clear_checklist: a returned application is checked again from
  scratch. On both "Return to applicant" moves.
- core.workflow_transitions.allowed_on_hold: the move may be made while an
  open blocking flag holds the case, and resolves those flags with its
  reason. On the desk's Reject (SCREENS.md S2) [CONFIRM].
"""
import sqlalchemy as sa
from alembic import op

revision = "0029"
down_revision = "0028"
branch_labels = None
depends_on = None

APP_ROLE = "motie_app"

# [CONFIRM] The wording of the ECOWAS ETLS list checks, with the ETLS desk.
ITEMS = [
    ("ecowas_exporter_listed", "The exporter's ETLS approval number is on the ECOWAS ETLS list", 1),
    ("ecowas_product_covered", "On the ECOWAS ETLS list, the product approval covers these goods", 2),
]

_FL_MOVES = """
    FROM core.workflow_transitions x
    JOIN core.workflows w ON w.id = x.workflow_id AND w.code = 'etls_facility_letter'
    JOIN core.workflow_statuses f ON f.id = x.from_status_id
    JOIN core.workflow_statuses t ON t.id = x.to_status_id
"""


def upgrade() -> None:
    op.create_table(
        "checklist_items",
        sa.Column("id", sa.SmallInteger, sa.Identity(), primary_key=True),
        sa.Column("workflow_id", sa.SmallInteger, nullable=False),
        # The step at which it's ticked: same workflow, so a composite key.
        sa.Column("status_id", sa.Integer, nullable=False),
        sa.Column("code", sa.Text, nullable=False),
        sa.Column("label", sa.Text, nullable=False),
        sa.Column("sort_order", sa.SmallInteger, nullable=False),
        sa.ForeignKeyConstraint(
            ["workflow_id", "status_id"],
            ["core.workflow_statuses.workflow_id", "core.workflow_statuses.id"],
            name="checklist_items_status_fkey",
        ),
        sa.UniqueConstraint("workflow_id", "code", name="checklist_items_code_key"),
        schema="core",
    )
    op.create_table(
        "case_ticks",
        sa.Column("case_id", sa.BigInteger, sa.ForeignKey("core.cases.id"), primary_key=True),
        sa.Column("item_id", sa.SmallInteger, sa.ForeignKey("core.checklist_items.id"), primary_key=True),
        sa.Column("ticked_by", sa.BigInteger, sa.ForeignKey("core.users.id"), nullable=False),
        sa.Column("ticked_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        schema="core",
    )
    for code, label, order in ITEMS:
        op.execute(
            f"""
            INSERT INTO core.checklist_items (workflow_id, status_id, code, label, sort_order)
            SELECT w.id, s.id, '{code}', '{label.replace("'", "''")}', {order}
            FROM core.workflows w
            JOIN core.workflow_statuses s ON s.workflow_id = w.id AND s.code = 'originals_received'
            WHERE w.code = 'etls_facility_letter'
            """
        )
    op.execute(
        f"""
        INSERT INTO core.transition_checks (transition_id, check_code)
        SELECT x.id, 'checklist_complete' {_FL_MOVES}
        WHERE f.code = 'originals_received' AND t.code = 'verified'
        """
    )
    op.execute(
        f"""
        INSERT INTO core.transition_effects (transition_id, effect_code)
        SELECT x.id, 'clear_checklist' {_FL_MOVES}
        WHERE t.code = 'returned'
        """
    )

    op.add_column(
        "workflow_transitions",
        sa.Column("allowed_on_hold", sa.Boolean, nullable=False, server_default=sa.false()),
        schema="core",
    )
    op.execute(
        f"""
        UPDATE core.workflow_transitions SET allowed_on_hold = true
        WHERE id IN (SELECT x.id {_FL_MOVES} WHERE f.code = 'originals_received' AND t.code = 'rejected')
        """
    )

    op.execute(f"GRANT SELECT ON core.checklist_items TO {APP_ROLE}")
    op.execute(f"GRANT SELECT, INSERT, DELETE ON core.case_ticks TO {APP_ROLE}")


def downgrade() -> None:
    op.drop_column("workflow_transitions", "allowed_on_hold", schema="core")
    op.execute("DELETE FROM core.transition_effects WHERE effect_code = 'clear_checklist'")
    op.execute("DELETE FROM core.transition_checks WHERE check_code = 'checklist_complete'")
    op.drop_table("case_ticks", schema="core")
    op.drop_table("checklist_items", schema="core")
