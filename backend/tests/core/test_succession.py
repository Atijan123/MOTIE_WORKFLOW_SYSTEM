"""The succession order table: who is next in line when a post's holder is away.

Who actually gets to act (which needs absences) is tested in test_absences.py.
"""

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError

from app.core.identity.models import Position
from app.core.workflow.models import Workflow
from app.core.workflow.succession import succession_order

pytestmark = pytest.mark.anyio


@pytest.fixture
async def ids(db_session):
    positions = {p.code: p.id for p in (await db_session.scalars(select(Position))).all()}
    etls = await db_session.scalar(select(Workflow.id).where(Workflow.code == "etls_application"))
    return positions, etls


async def test_general_chain_is_minister_then_ps_then_dps(db_session, ids):
    positions, etls = ids
    order = await succession_order(db_session, positions["minister"], etls)
    assert order == [positions["permanent_secretary"], positions["dps_admin_finance"]]
    assert await succession_order(db_session, positions["permanent_secretary"], etls) == [
        positions["dps_admin_finance"]
    ]


async def test_the_director_has_no_successor_post(db_session, ids):
    """The authorised signatories list replaced "DPS Admin & Finance acts for
    the Director" (0040; see test_signing_rules.py)."""
    positions, etls = ids
    assert await succession_order(db_session, positions["director_of_industry"], etls) == []


async def test_posts_without_a_rule_have_nobody_next_in_line(db_session, ids):
    positions, etls = ids
    assert await succession_order(db_session, positions["industry_officer"], etls) == []


async def _add(session, position, rank, successor, workflow=None):
    await session.execute(
        text(
            "INSERT INTO core.succession_orders (position_id, workflow_id, rank, successor_position_id) "
            "SELECT p.id, (SELECT id FROM core.workflows WHERE code = :wf), :rank, n.id "
            "FROM core.positions p, core.positions n WHERE p.code = :p AND n.code = :n"
        ),
        {"p": position, "n": successor, "rank": rank, "wf": workflow},
    )


async def test_a_workflow_rule_replaces_the_general_one(owner_session, ids):
    positions, etls = ids
    # An ETLS-only rule for the Minister: the DPS straight away, skipping the PS.
    await _add(owner_session, "minister", 1, "dps_admin_finance", workflow="etls_application")

    assert await succession_order(owner_session, positions["minister"], etls) == [
        positions["dps_admin_finance"]
    ]
    assert await succession_order(owner_session, positions["minister"], etls + 1000) == [
        positions["permanent_secretary"],
        positions["dps_admin_finance"],
    ]


@pytest.mark.parametrize(
    "position, rank, successor",
    [
        ("minister", 1, "director_of_industry"),  # rank 1 already taken (general rules too)
        ("minister", 3, "permanent_secretary"),  # the PS is already in the Minister's line
        ("minister", 3, "minister"),  # a post can't succeed itself
        ("minister", 0, "director_of_industry"),  # ranks start at 1
    ],
    ids=["same-rank", "same-successor", "self", "rank-zero"],
)
async def test_database_refuses_broken_rules(owner_session, position, rank, successor):
    with pytest.raises(IntegrityError):
        await _add(owner_session, position, rank, successor)
