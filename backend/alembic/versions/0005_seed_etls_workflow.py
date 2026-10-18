"""Seed a placeholder ETLS application workflow.

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-18

[CONFIRM] Every status, transition and role below is a placeholder based on the
chain of command in CLAUDE.md (Records -> Minister, or PS -> Directorate ->
officer). Check it with the Ministry before real use. Changing it later means a
new migration, not editing this one.
"""
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. The workflow itself. The start role is looked up by code, so this works
    #    whatever id the role got.
    op.execute(
        """
        INSERT INTO core.workflows (code, name, start_role_id)
        SELECT 'etls_application', 'ETLS application', r.id
        FROM core.roles r
        WHERE r.code = 'applicant'
        """
    )

    # 2. Its statuses. VALUES (...) builds a small inline table of rows; we join
    #    it to the workflow row to get workflow_id.
    op.execute(
        """
        INSERT INTO core.workflow_statuses (workflow_id, code, name, is_initial, is_final)
        SELECT w.id, s.code, s.name, s.is_initial, s.is_final
        FROM core.workflows w
        CROSS JOIN (VALUES
            ('submitted',        'Submitted',                 true,  false),
            ('with_minister',    'With the Minister',         false, false),
            ('with_directorate', 'With the Directorate',      false, false),
            ('with_officer',     'With the subject officer',  false, false),
            ('approved',         'Approved',                  false, true),
            ('rejected',         'Rejected',                  false, true)
        ) AS s(code, name, is_initial, is_final)
        WHERE w.code = 'etls_application'
        """
    )

    # 3. The allowed moves, written with codes. The joins turn each code into
    #    the matching id. If a code is misspelt, the join finds no row and that
    #    transition is silently skipped, so tests/core/test_workflow_definitions.py
    #    checks the expected count.
    op.execute(
        """
        INSERT INTO core.workflow_transitions
            (workflow_id, from_status_id, to_status_id, required_role_id, name)
        SELECT w.id, f.id, t.id, r.id, x.name
        FROM (VALUES
            ('submitted',        'with_minister',    'records_officer',     'Register and forward to the Minister'),
            ('with_minister',    'with_directorate', 'minister',            'Minute to the Directorate'),
            ('with_minister',    'with_directorate', 'permanent_secretary', 'Minute to the Directorate (for the Minister)'),
            ('with_directorate', 'with_officer',     'director',            'Assign to an officer'),
            ('with_officer',     'with_directorate', 'officer',             'Return to the Directorate'),
            ('with_officer',     'approved',         'officer',             'Approve'),
            ('with_officer',     'rejected',         'officer',             'Reject')
        ) AS x(from_code, to_code, role_code, name)
        JOIN core.workflows w ON w.code = 'etls_application'
        JOIN core.workflow_statuses f ON f.workflow_id = w.id AND f.code = x.from_code
        JOIN core.workflow_statuses t ON t.workflow_id = w.id AND t.code = x.to_code
        JOIN core.roles r ON r.code = x.role_code
        """
    )


def downgrade() -> None:
    # Delete in the reverse order of the foreign keys: moves, then statuses, then the workflow.
    for table in ("workflow_transitions", "workflow_statuses"):
        op.execute(
            f"""
            DELETE FROM core.{table}
            WHERE workflow_id = (SELECT id FROM core.workflows WHERE code = 'etls_application')
            """
        )
    op.execute("DELETE FROM core.workflows WHERE code = 'etls_application'")
