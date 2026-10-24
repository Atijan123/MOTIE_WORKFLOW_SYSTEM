"""What the API's database user (motie_app) can and can't do.

db_session logs in as motie_app, exactly like the running API, so these tests
show what an attacker who took over the API could do with its connection.
"""

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

pytestmark = pytest.mark.anyio


async def test_app_user_is_not_a_superuser_and_owns_nothing(db_session):
    row = (
        await db_session.execute(
            text(
                "SELECT current_user, r.rolsuper, r.rolcreaterole, r.rolcreatedb, "
                "(SELECT count(*) FROM pg_class c WHERE c.relowner = r.oid) AS owned "
                "FROM pg_roles r WHERE r.rolname = current_user"
            )
        )
    ).one()
    assert row.current_user == "motie_app"
    assert (row.rolsuper, row.rolcreaterole, row.rolcreatedb) == (False, False, False)
    assert row.owned == 0


@pytest.mark.parametrize(
    "statement",
    [
        "ALTER TABLE core.audit_log DISABLE TRIGGER audit_log_no_update_delete",
        "ALTER TABLE core.audit_log DISABLE TRIGGER ALL",
        "DROP TRIGGER audit_log_no_update_delete ON core.audit_log",
        "CREATE OR REPLACE FUNCTION core.audit_log_block_changes() RETURNS trigger "
        "LANGUAGE plpgsql AS $$ BEGIN RETURN OLD; END $$",
        "DROP TABLE core.audit_log",
    ],
    ids=["disable-one-trigger", "disable-all-triggers", "drop-trigger", "replace-function", "drop-table"],
)
async def test_app_user_cannot_switch_off_the_audit_protection(db_session, statement):
    # Only the owner of a table or function may alter it. (Replacing the function
    # fails one step earlier: the app can't create anything in core at all.)
    with pytest.raises(DBAPIError, match="must be owner|permission denied"):
        await db_session.execute(text(statement))


async def test_app_user_cannot_skip_triggers_with_replication_mode(db_session):
    # session_replication_role = replica makes Postgres skip ordinary triggers.
    # Only superusers may set it.
    with pytest.raises(DBAPIError, match="permission denied"):
        await db_session.execute(text("SET session_replication_role = replica"))


@pytest.mark.parametrize(
    "statement",
    [
        "CREATE TABLE core.sneaky (id int)",
        "DELETE FROM core.users",
        "DELETE FROM core.cases",
        "UPDATE core.workflow_transitions SET name = 'x'",
        "INSERT INTO core.roles (code, name) VALUES ('king', 'King')",
        "UPDATE core.positions SET reports_to_id = NULL",
        # The app may revoke a delegation, but never move its dates or posts.
        "UPDATE core.delegations SET ends_on = ends_on + 30",
        "DELETE FROM core.delegations",
        "UPDATE core.absences SET ends_on = ends_on + 30",
        "DELETE FROM core.absences",
        "INSERT INTO core.succession_orders (position_id, rank, successor_position_id) VALUES (1, 9, 2)",
        # An issued letter is never changed or removed, and the app can't add effects to moves.
        "UPDATE core.issued_documents SET sha256 = 'x'",
        "DELETE FROM core.issued_documents",
        "INSERT INTO core.transition_effects (transition_id, effect_code) VALUES (1, 'x')",
        # The applicant's form may be edited (while a draft), but never moved to another case.
        "UPDATE etls.facility_letters SET case_id = case_id + 1",
    ],
    ids=[
        "create-table",
        "delete-users",
        "delete-cases",
        "edit-workflow",
        "add-role",
        "edit-org-chart",
        "stretch-delegation",
        "delete-delegation",
        "stretch-absence",
        "delete-absence",
        "add-succession-rule",
        "edit-issued-document",
        "delete-issued-document",
        "add-transition-effect",
        "move-a-form-to-another-case",
    ],
)
async def test_app_user_cannot_do_what_it_was_never_granted(db_session, statement):
    with pytest.raises(DBAPIError, match="permission denied"):
        await db_session.execute(text(statement))


async def test_every_table_is_owned_by_motie_owner_and_readable_by_the_app(owner_session):
    # A new migration that forgets its GRANT shows up here by name, instead of
    # as a "permission denied" somewhere in the API.
    rows = (
        await owner_session.execute(
            text(
                "SELECT schemaname || '.' || tablename AS name, tableowner, "
                "has_table_privilege('motie_app', schemaname || '.' || tablename, 'SELECT') AS readable "
                "FROM pg_tables WHERE schemaname IN ('core', 'etls')"
            )
        )
    ).all()
    assert rows, "no tables found in core"
    assert {r.name for r in rows if r.tableowner != "motie_owner"} == set()
    assert {r.name for r in rows if not r.readable} == set()
