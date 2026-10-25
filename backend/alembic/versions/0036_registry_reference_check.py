"""Signing waits for the registry file reference to be set, on a real server.

Revision ID: 0036
Revises: 0035
Create Date: 2026-10-25

The facility letter prints the Ministry's registry file reference
(FACILITY_LETTER_REFERENCE_FORMAT). On a developer's machine
(APP_ENV=development) it defaults to the example from the spec,
"ADM 151/420/01/PART IV". With APP_ENV=production there is no default: a
letter must never go out with an example reference. The new check
etls_registry_reference_set on the PS's "Sign" move says so in blocked_by
until the setting is filled in.
"""
from alembic import op

revision = "0036"
down_revision = "0035"
branch_labels = None
depends_on = None

_SIGN_MOVE = """
    FROM core.workflow_transitions x
    JOIN core.workflows w ON w.id = x.workflow_id AND w.code = 'etls_facility_letter'
    JOIN core.workflow_statuses f ON f.id = x.from_status_id AND f.code = 'verified'
    JOIN core.workflow_statuses t ON t.id = x.to_status_id AND t.code = 'signed'
"""


def upgrade() -> None:
    op.execute(
        f"""
        INSERT INTO core.transition_checks (transition_id, check_code)
        SELECT x.id, 'etls_registry_reference_set' {_SIGN_MOVE}
        """
    )


def downgrade() -> None:
    op.execute("DELETE FROM core.transition_checks WHERE check_code = 'etls_registry_reference_set'")
