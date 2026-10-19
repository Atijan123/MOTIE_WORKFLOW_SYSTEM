"""Departments, positions and who holds them."""

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError

from app.core.audit.service import history
from app.core.identity.models import Position
from app.core.identity.service import UnknownPosition, assign_position, remove_position

pytestmark = pytest.mark.anyio


async def test_placeholder_org_chart_is_seeded(db_session):
    positions = {p.code: p for p in (await db_session.scalars(select(Position))).all()}
    by_id = {p.id: p for p in positions.values()}

    assert set(positions) == {
        "minister",
        "permanent_secretary",
        "records_officer",
        "director_of_trade",
        "trade_officer",
        "dps_admin_finance",
        "director_of_industry",
        "industry_officer",
        "etls_desk_officer",
    }
    boss_of = {p.code: by_id[p.reports_to_id].code for p in positions.values() if p.reports_to_id}
    assert boss_of == {
        "permanent_secretary": "minister",
        "records_officer": "permanent_secretary",
        "director_of_trade": "permanent_secretary",
        "trade_officer": "director_of_trade",
        "dps_admin_finance": "permanent_secretary",
        "director_of_industry": "permanent_secretary",
        "industry_officer": "director_of_industry",
        "etls_desk_officer": "director_of_industry",
    }


async def test_every_chain_of_command_ends_at_one_top_post(db_session):
    # A loop in reports-to ("A reports to B, B reports to A") would make
    # "who is above this officer?" run forever. Walk up from every post.
    positions = {p.id: p for p in (await db_session.scalars(select(Position))).all()}
    tops = {p.code for p in positions.values() if p.reports_to_id is None}
    assert tops == {"minister"}

    for start in positions.values():
        seen, current = set(), start
        while current.reports_to_id is not None:
            assert current.id not in seen, f"reports-to loop through {current.code}"
            seen.add(current.id)
            current = positions[current.reports_to_id]
        assert current.code == "minister"


async def test_a_post_cannot_report_to_itself(owner_session):
    with pytest.raises(IntegrityError):
        await owner_session.execute(
            text("UPDATE core.positions SET reports_to_id = id WHERE code = 'minister'")
        )


async def test_assigning_a_position_is_audited(db_session, make_user):
    admin = await make_user("admin")
    user = await make_user("director")

    assert await assign_position(
        db_session, user=user, position_code="director_of_trade", actor=admin
    )

    assert user.position_codes == {"director_of_trade"}
    events = await history(db_session, "user", user.id)
    assert [(e.action, e.actor_user_id, e.details) for e in events] == [
        ("position.assigned", admin.id, {"position": "director_of_trade"})
    ]


async def test_assigning_twice_changes_nothing(db_session, make_user):
    user = await make_user("officer", positions=["trade_officer"])

    assert not await assign_position(db_session, user=user, position_code="trade_officer", actor=None)

    assert user.position_codes == {"trade_officer"}
    assert len(await history(db_session, "user", user.id)) == 1


async def test_a_user_can_hold_several_posts_and_a_post_several_users(db_session, make_user):
    acting = await make_user("officer", positions=["trade_officer", "director_of_trade"])
    colleague = await make_user("officer", positions=["trade_officer"])

    assert acting.position_codes == {"trade_officer", "director_of_trade"}
    assert colleague.position_codes == {"trade_officer"}


async def test_removing_a_position_is_audited(db_session, make_user):
    user = await make_user("officer", positions=["trade_officer"])

    assert await remove_position(db_session, user=user, position_code="trade_officer", actor=None)
    assert not await remove_position(db_session, user=user, position_code="trade_officer", actor=None)

    assert user.position_codes == set()
    events = await history(db_session, "user", user.id)
    assert [e.action for e in events] == ["position.assigned", "position.removed"]


async def test_unknown_position_is_refused(db_session, make_user):
    user = await make_user("officer")
    with pytest.raises(UnknownPosition):
        await assign_position(db_session, user=user, position_code="king", actor=None)
