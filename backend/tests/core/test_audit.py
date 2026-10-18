import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.core.audit.service import history, record_event

pytestmark = pytest.mark.anyio


async def test_record_event_and_read_history(db_session, make_user):
    user = await make_user("officer")
    record_event(db_session, actor=user, action="case.created", entity_type="case", entity_id=1)
    record_event(
        db_session,
        actor=user,
        action="case.status_changed",
        entity_type="case",
        entity_id=1,
        details={"from": "submitted", "to": "with_minister"},
    )
    record_event(db_session, actor=None, action="case.created", entity_type="case", entity_id=2)
    await db_session.commit()

    events = await history(db_session, "case", 1)

    assert [e.action for e in events] == ["case.created", "case.status_changed"]
    assert events[0].actor_user_id == user.id
    assert events[1].details == {"from": "submitted", "to": "with_minister"}
    assert events[0].occurred_at is not None


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE core.audit_log SET action = 'tampered'",
        "DELETE FROM core.audit_log",
        "TRUNCATE core.audit_log",
    ],
    ids=["update", "delete", "truncate"],
)
async def test_audit_log_rejects_changes(db_session, statement):
    record_event(db_session, actor=None, action="x", entity_type="case", entity_id=1)
    await db_session.commit()

    # Even raw SQL that bypasses our Python code is refused by the database.
    with pytest.raises(DBAPIError, match="append-only"):
        await db_session.execute(text(statement))
