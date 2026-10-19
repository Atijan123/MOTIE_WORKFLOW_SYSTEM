"""What the API's database user (motie_app) may do with each table.

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-19

The role itself is created by db/init/10-db-users.sh. This migration fails with
"role motie_app does not exist" if that script hasn't run, which is what we want.

Every later migration that adds a table must grant on it too, the way this one
does. If it forgets, the API gets "permission denied" (it fails closed, never
open), and tests/core/test_db_privileges.py names the table nobody granted.
"""
from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None

APP_ROLE = "motie_app"


def upgrade() -> None:
    # USAGE lets the role look up objects in the schema; it grants no table access.
    op.execute(f"GRANT USAGE ON SCHEMA core TO {APP_ROLE}")

    # Written only by migrations ("workflows are data", loaded by migrations).
    op.execute(
        "GRANT SELECT ON core.roles, core.workflows, core.workflow_statuses, "
        f"core.workflow_transitions TO {APP_ROLE}"
    )
    # Users and cases are never deleted (users are deactivated, cases end in a
    # final status), so DELETE isn't granted: the database enforces that rule too.
    op.execute(f"GRANT SELECT, INSERT, UPDATE ON core.users, core.cases TO {APP_ROLE}")
    # Removing a role from a user deletes its link row.
    op.execute(f"GRANT SELECT, INSERT, DELETE ON core.user_roles TO {APP_ROLE}")
    # Append-only: no UPDATE, DELETE or TRUNCATE. The trigger from 0003 still
    # guards against the owner; this stops the app before the trigger is reached.
    op.execute(f"GRANT SELECT, INSERT ON core.audit_log TO {APP_ROLE}")


def downgrade() -> None:
    op.execute(f"REVOKE ALL ON ALL TABLES IN SCHEMA core FROM {APP_ROLE}")
    op.execute(f"REVOKE USAGE ON SCHEMA core FROM {APP_ROLE}")
