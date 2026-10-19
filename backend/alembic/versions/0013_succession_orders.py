"""Succession orders: who acts for a post when its holder is absent.

Revision ID: 0013
Revises: 0012
Create Date: 2026-10-19

Each row says: "when <position> is absent, <successor> is next in line, at
<rank>", either for every workflow (workflow_id empty) or for one workflow. If a
post has rows for a workflow, those replace its general rows for that workflow.

Unlike a delegation (step 4d), which a person sets up for their own absence,
succession is the Ministry's standing rule. It applies by itself once an absence
is recorded (step 5c).
"""
import sqlalchemy as sa
from alembic import op

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None

APP_ROLE = "motie_app"


def upgrade() -> None:
    op.create_table(
        "succession_orders",
        sa.Column("id", sa.SmallInteger, sa.Identity(), primary_key=True),
        sa.Column("position_id", sa.SmallInteger, sa.ForeignKey("core.positions.id"), nullable=False),
        sa.Column("workflow_id", sa.SmallInteger, sa.ForeignKey("core.workflows.id"), nullable=True),
        sa.Column("rank", sa.SmallInteger, nullable=False),  # 1 = first in line
        sa.Column(
            "successor_position_id", sa.SmallInteger, sa.ForeignKey("core.positions.id"), nullable=False
        ),
        sa.CheckConstraint("rank >= 1", name="succession_orders_rank_positive"),
        sa.CheckConstraint("successor_position_id <> position_id", name="succession_orders_not_self"),
        # NULLS NOT DISTINCT (Postgres 15+): normally two NULLs never count as
        # equal, so two general rows (workflow_id empty) could share a rank. This
        # makes "empty" count as one value, like any workflow id.
        sa.UniqueConstraint(
            "position_id", "workflow_id", "rank",
            name="succession_orders_rank_key", postgresql_nulls_not_distinct=True,
        ),
        sa.UniqueConstraint(
            "position_id", "workflow_id", "successor_position_id",
            name="succession_orders_successor_key", postgresql_nulls_not_distinct=True,
        ),
        schema="core",
    )

    # Confirmed: general chain Minister -> PS -> DPS; for ETLS, the Director of
    # Industry and Investment -> DPS Administration and Finance.
    # [CONFIRM] Which DPS covers the Minister's step when both the Minister and
    # the PS are away. DPS Administration and Finance is the only DPS post we
    # know of, so it's used for the general chain until the Ministry says.
    op.execute(
        """
        INSERT INTO core.succession_orders (position_id, workflow_id, rank, successor_position_id)
        SELECT p.id, w.id, s.rank, n.id
        FROM (VALUES
            ('minister',             NULL,               1, 'permanent_secretary'),
            ('minister',             NULL,               2, 'dps_admin_finance'),
            ('permanent_secretary',  NULL,               1, 'dps_admin_finance'),
            ('director_of_industry', 'etls_application', 1, 'dps_admin_finance')
        ) AS s(position_code, workflow_code, rank, successor_code)
        JOIN core.positions p ON p.code = s.position_code
        JOIN core.positions n ON n.code = s.successor_code
        LEFT JOIN core.workflows w ON w.code = s.workflow_code
        """
    )

    # Standing rules, loaded by migrations like workflows: the app only reads them.
    op.execute(f"GRANT SELECT ON core.succession_orders TO {APP_ROLE}")


def downgrade() -> None:
    op.drop_table("succession_orders", schema="core")
