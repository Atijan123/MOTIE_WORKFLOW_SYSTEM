"""Workflow moves require a position instead of a role.

Revision ID: 0009
Revises: 0008
Create Date: 2026-10-19

Until now, each transition named the *role* allowed to make it. Approvals belong
to posts (CLAUDE.md), so each transition now names a *position*. Existing rows
are converted with the mapping below.
"""
import sqlalchemy as sa
from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None

# [CONFIRM] Which post makes each kind of move, following the placeholder org
# chart in 0008. "officer" means a Trade Officer for now: ETLS is handled by the
# Directorate of Trade.
ROLE_TO_POSITION = [
    ("records_officer", "records_officer"),
    ("minister", "minister"),
    ("permanent_secretary", "permanent_secretary"),
    ("director", "director_of_trade"),
    ("officer", "trade_officer"),
]


def _mapping_sql() -> str:
    # Our own constants, not user input, so building the VALUES list is safe.
    return ", ".join(f"('{role}', '{position}')" for role, position in ROLE_TO_POSITION)


def upgrade() -> None:
    op.add_column(
        "workflow_transitions",
        sa.Column(
            "required_position_id",
            sa.SmallInteger,
            sa.ForeignKey("core.positions.id", name="workflow_transitions_required_position_id_fkey"),
            nullable=True,
        ),
        schema="core",
    )
    op.execute(
        f"""
        UPDATE core.workflow_transitions t SET required_position_id = p.id
        FROM (VALUES {_mapping_sql()}) AS m(role_code, position_code)
        JOIN core.roles r ON r.code = m.role_code
        JOIN core.positions p ON p.code = m.position_code
        WHERE t.required_role_id = r.id
        """
    )
    # If a transition's role isn't in the mapping, it is still empty here and
    # this fails, so no move can silently lose its approver.
    op.alter_column("workflow_transitions", "required_position_id", nullable=False, schema="core")

    op.drop_constraint("workflow_transitions_move_key", "workflow_transitions", schema="core")
    op.drop_column("workflow_transitions", "required_role_id", schema="core")  # drops its FK too
    op.create_unique_constraint(
        "workflow_transitions_move_key",
        "workflow_transitions",
        ["from_status_id", "to_status_id", "required_position_id"],
        schema="core",
    )


def downgrade() -> None:
    op.add_column(
        "workflow_transitions",
        sa.Column(
            "required_role_id",
            sa.SmallInteger,
            sa.ForeignKey("core.roles.id", name="workflow_transitions_required_role_id_fkey"),
            nullable=True,
        ),
        schema="core",
    )
    op.execute(
        f"""
        UPDATE core.workflow_transitions t SET required_role_id = r.id
        FROM (VALUES {_mapping_sql()}) AS m(role_code, position_code)
        JOIN core.roles r ON r.code = m.role_code
        JOIN core.positions p ON p.code = m.position_code
        WHERE t.required_position_id = p.id
        """
    )
    op.alter_column("workflow_transitions", "required_role_id", nullable=False, schema="core")
    op.drop_constraint("workflow_transitions_move_key", "workflow_transitions", schema="core")
    op.drop_column("workflow_transitions", "required_position_id", schema="core")
    op.create_unique_constraint(
        "workflow_transitions_move_key",
        "workflow_transitions",
        ["from_status_id", "to_status_id", "required_role_id"],
        schema="core",
    )
