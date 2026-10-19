"""Departments, positions (with reports-to), and the users holding them.

Revision ID: 0008
Revises: 0007
Create Date: 2026-10-19

A position is a post in the Ministry ("Director of Trade"), not a person.
Approvals will attach to positions, so when a new Director arrives, they take
over the post and nothing in the workflow tables changes.

[CONFIRM] The departments and positions seeded below are placeholders based on
the chain of command in CLAUDE.md. Check the real organisation chart with the
Ministry. Changing it later means a new migration, not editing this one.
"""
import sqlalchemy as sa
from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None

APP_ROLE = "motie_app"


def upgrade() -> None:
    op.create_table(
        "departments",
        sa.Column("id", sa.SmallInteger, sa.Identity(), primary_key=True),
        sa.Column("code", sa.Text, nullable=False, unique=True),
        sa.Column("name", sa.Text, nullable=False),
        schema="core",
    )

    # reports_to_id points at another row of this same table: the post above
    # this one. Empty only for the top of the Ministry (the Minister).
    op.create_table(
        "positions",
        sa.Column("id", sa.SmallInteger, sa.Identity(), primary_key=True),
        sa.Column("code", sa.Text, nullable=False, unique=True),
        sa.Column("title", sa.Text, nullable=False),
        sa.Column(
            "department_id", sa.SmallInteger, sa.ForeignKey("core.departments.id"), nullable=False
        ),
        sa.Column("reports_to_id", sa.SmallInteger, sa.ForeignKey("core.positions.id"), nullable=True),
        sa.CheckConstraint("reports_to_id <> id", name="positions_not_own_boss"),
        schema="core",
    )

    # Who holds which post. A user can hold several posts (e.g. acting Director
    # while still a Trade Officer), and a post can have several holders (e.g.
    # several Trade Officers). Unlike user_roles, rows here are never removed by
    # cascade: users aren't deleted, and the audit log records every change.
    op.create_table(
        "position_holders",
        sa.Column("position_id", sa.SmallInteger, sa.ForeignKey("core.positions.id"), primary_key=True),
        sa.Column("user_id", sa.BigInteger, sa.ForeignKey("core.users.id"), primary_key=True),
        sa.Column(
            "assigned_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        schema="core",
    )
    # The primary key starts with position_id, so it already finds "who holds
    # this post?". This index answers "which posts does this user hold?", asked
    # on every status change.
    op.create_index("position_holders_user_idx", "position_holders", ["user_id"], schema="core")

    op.execute(
        """
        INSERT INTO core.departments (code, name) VALUES
            ('ministers_office',  'Office of the Minister'),
            ('ps_office',         'Office of the Permanent Secretary'),
            ('registry',          'Registry'),
            ('trade_directorate', 'Directorate of Trade')
        """
    )
    # Two passes: insert every post first, then link each to its boss by code,
    # because a post's boss may not exist yet while we're still inserting.
    op.execute(
        """
        INSERT INTO core.positions (code, title, department_id)
        SELECT p.code, p.title, d.id
        FROM (VALUES
            ('minister',            'Minister',            'ministers_office'),
            ('permanent_secretary', 'Permanent Secretary', 'ps_office'),
            ('records_officer',     'Records Officer',     'registry'),
            ('director_of_trade',   'Director of Trade',   'trade_directorate'),
            ('trade_officer',       'Trade Officer',       'trade_directorate')
        ) AS p(code, title, department_code)
        JOIN core.departments d ON d.code = p.department_code
        """
    )
    op.execute(
        """
        UPDATE core.positions p SET reports_to_id = boss.id
        FROM (VALUES
            ('permanent_secretary', 'minister'),
            ('records_officer',     'permanent_secretary'),
            ('director_of_trade',   'permanent_secretary'),
            ('trade_officer',       'director_of_trade')
        ) AS r(code, boss_code)
        JOIN core.positions boss ON boss.code = r.boss_code
        WHERE p.code = r.code
        """
    )

    # The organisation chart is loaded by migrations, like workflows. The app
    # only records who holds which post.
    op.execute(f"GRANT SELECT ON core.departments, core.positions TO {APP_ROLE}")
    op.execute(f"GRANT SELECT, INSERT, DELETE ON core.position_holders TO {APP_ROLE}")


def downgrade() -> None:
    op.drop_table("position_holders", schema="core")
    op.drop_table("positions", schema="core")
    op.drop_table("departments", schema="core")
