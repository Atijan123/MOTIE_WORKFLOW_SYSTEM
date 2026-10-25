import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.core.audit.service import history, record_event

pytestmark = pytest.mark.anyio


async def test_record_event_and_read_history(db_session, make_user):
    # entity_type "test" so these rows can't mix with real case events.
    user = await make_user("officer")
    record_event(db_session, actor=user, action="case.created", entity_type="test", entity_id=1)
    record_event(
        db_session,
        actor=user,
        action="case.status_changed",
        entity_type="test",
        entity_id=1,
        details={"from": "submitted", "to": "with_minister"},
    )
    record_event(db_session, actor=None, action="case.created", entity_type="test", entity_id=2)
    await db_session.commit()

    events = await history(db_session, "test", 1)

    assert [e.action for e in events] == ["case.created", "case.status_changed"]
    assert events[0].actor_user_id == user.id
    assert events[1].details == {"from": "submitted", "to": "with_minister"}
    assert events[0].occurred_at is not None


CHANGES = pytest.mark.parametrize(
    "statement",
    [
        "UPDATE core.audit_log SET action = 'tampered'",
        "DELETE FROM core.audit_log",
        # CASCADE: core.notifications points at audit rows (0033), and without it
        # that foreign key would refuse first. The test is about the trigger.
        "TRUNCATE core.audit_log CASCADE",
    ],
    ids=["update", "delete", "truncate"],
)


@CHANGES
async def test_app_user_has_no_right_to_change_audit_rows(db_session, statement):
    record_event(db_session, actor=None, action="x", entity_type="test", entity_id=1)
    await db_session.commit()

    # motie_app was never granted UPDATE, DELETE or TRUNCATE, so Postgres
    # refuses before the trigger is even reached.
    with pytest.raises(DBAPIError, match="permission denied"):
        await db_session.execute(text(statement))


@CHANGES
async def test_trigger_stops_even_the_table_owner(owner_session, statement):
    record_event(owner_session, actor=None, action="x", entity_type="test", entity_id=1)
    await owner_session.commit()

    # The owner has every privilege, so here the trigger is what refuses.
    with pytest.raises(DBAPIError, match="append-only"):
        await owner_session.execute(text(statement))
