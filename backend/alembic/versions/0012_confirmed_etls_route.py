"""The ETLS route and chain of command confirmed by the Ministry (2026-10-19).

Revision ID: 0012
Revises: 0011
Create Date: 2026-10-19

Confirmed:
- General chain of command: Minister -> Permanent Secretary -> Deputy PS.
- ETLS route: Records -> Minister -> PS -> Director of Industry and Investment,
  who signs the file and assigns (minutes) it to an officer.

So this migration adds the Directorate of Industry and Investment, its Director
and officer posts, and the DPS Administration and Finance post. It reroutes ETLS
through the PS. The ETLS steps now go to the Industry and Investment posts
instead of the Trade ones; the Trade posts stay in the org chart.

The status 'with_directorate' is renamed, not replaced, so any case already in
it keeps a valid status (cases point at the status id).
"""
from alembic import op

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None

ETLS = "(SELECT id FROM core.workflows WHERE code = 'etls_application')"


def _status(code: str) -> str:
    return f"(SELECT id FROM core.workflow_statuses WHERE workflow_id = {ETLS} AND code = '{code}')"


def _position(code: str) -> str:
    return f"(SELECT id FROM core.positions WHERE code = '{code}')"


def upgrade() -> None:
    op.execute(
        """
        INSERT INTO core.departments (code, name) VALUES
            ('industry_directorate', 'Directorate of Industry and Investment'),
            ('admin_finance',        'Administration and Finance')
        """
    )
    # [CONFIRM] Post titles for the DPS and the ETLS officer, and which
    # department the DPS sits in.
    op.execute(
        """
        INSERT INTO core.positions (code, title, department_id, reports_to_id)
        SELECT p.code, p.title, d.id, boss.id
        FROM (VALUES
            ('dps_admin_finance',    'Deputy Permanent Secretary, Administration and Finance', 'admin_finance',        'permanent_secretary'),
            ('director_of_industry', 'Director of Industry and Investment',                    'industry_directorate', 'permanent_secretary')
        ) AS p(code, title, department_code, boss_code)
        JOIN core.departments d ON d.code = p.department_code
        JOIN core.positions boss ON boss.code = p.boss_code
        """
    )
    # A second statement, because its boss (director_of_industry) only exists now.
    op.execute(
        """
        INSERT INTO core.positions (code, title, department_id, reports_to_id)
        SELECT 'industry_officer', 'Industry and Investment Officer', d.id, boss.id
        FROM core.departments d, core.positions boss
        WHERE d.code = 'industry_directorate' AND boss.code = 'director_of_industry'
        """
    )

    # Statuses: the Directorate step becomes the Director's, and a PS step is added.
    op.execute(
        f"""
        UPDATE core.workflow_statuses
        SET code = 'with_director', name = 'With the Director of Industry and Investment'
        WHERE id = {_status('with_directorate')}
        """
    )
    op.execute(
        f"""
        INSERT INTO core.workflow_statuses (workflow_id, code, name)
        VALUES ({ETLS}, 'with_ps', 'With the Permanent Secretary')
        """
    )

    # Transitions. The Minister now minutes to the PS instead of the Directorate.
    op.execute(
        f"""
        UPDATE core.workflow_transitions
        SET to_status_id = {_status('with_ps')}, name = 'Minute to the Permanent Secretary'
        WHERE from_status_id = {_status('with_minister')}
          AND to_status_id = {_status('with_director')}
          AND required_position_id = {_position('minister')}
        """
    )
    op.execute(
        f"""
        INSERT INTO core.workflow_transitions
            (workflow_id, from_status_id, to_status_id, required_position_id, name)
        VALUES ({ETLS}, {_status('with_ps')}, {_status('with_director')},
                {_position('permanent_secretary')}, 'Minute to the Director')
        """
    )
    # One step covers both: the Director signs the file and minutes it to an officer.
    op.execute(
        f"""
        UPDATE core.workflow_transitions
        SET required_position_id = {_position('director_of_industry')},
            name = 'Sign and assign to an officer'
        WHERE from_status_id = {_status('with_director')}
          AND to_status_id = {_status('with_officer')}
        """
    )
    # [CONFIRM] What the officer does after the Director signs, and who may
    # reject a file. Until the Ministry says, the officer's three moves stay as
    # they were, now for the Industry and Investment officer post.
    op.execute(
        f"""
        UPDATE core.workflow_transitions
        SET required_position_id = {_position('industry_officer')}
        WHERE from_status_id = {_status('with_officer')}
        """
    )
    op.execute(
        f"""
        UPDATE core.workflow_transitions SET name = 'Return to the Director'
        WHERE from_status_id = {_status('with_officer')} AND to_status_id = {_status('with_director')}
        """
    )


def downgrade() -> None:
    op.execute(
        f"""
        UPDATE core.workflow_transitions SET name = 'Return to the Directorate'
        WHERE from_status_id = {_status('with_officer')} AND to_status_id = {_status('with_director')}
        """
    )
    op.execute(
        f"""
        UPDATE core.workflow_transitions SET required_position_id = {_position('trade_officer')}
        WHERE from_status_id = {_status('with_officer')}
        """
    )
    op.execute(
        f"""
        UPDATE core.workflow_transitions
        SET required_position_id = {_position('director_of_trade')}, name = 'Assign to an officer'
        WHERE from_status_id = {_status('with_director')} AND to_status_id = {_status('with_officer')}
        """
    )
    op.execute(
        f"DELETE FROM core.workflow_transitions WHERE from_status_id = {_status('with_ps')}"
    )
    op.execute(
        f"""
        UPDATE core.workflow_transitions
        SET to_status_id = {_status('with_director')}, name = 'Minute to the Directorate'
        WHERE from_status_id = {_status('with_minister')} AND to_status_id = {_status('with_ps')}
        """
    )
    # Fails if a case is still "With the PS": move it back by hand first, rather
    # than have a downgrade silently rewrite where a file is.
    op.execute(f"DELETE FROM core.workflow_statuses WHERE id = {_status('with_ps')}")
    op.execute(
        f"""
        UPDATE core.workflow_statuses SET code = 'with_directorate', name = 'With the Directorate'
        WHERE id = {_status('with_director')}
        """
    )
    op.execute(
        "DELETE FROM core.positions WHERE code IN ('industry_officer')"
    )
    op.execute(
        "DELETE FROM core.positions WHERE code IN ('director_of_industry', 'dps_admin_finance')"
    )
    op.execute("DELETE FROM core.departments WHERE code IN ('industry_directorate', 'admin_finance')")
