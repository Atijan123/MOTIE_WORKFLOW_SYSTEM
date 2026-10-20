"""Delegation: one post lets another act for it, for a date range.

Most tests use the Director of Industry and Investment going on leave and
delegating to the officer post (industry_officer), because the Director's move
(sign and assign to an officer) has no other approver.
"""

from datetime import timedelta

import pytest
from sqlalchemy import select

from app.core.audit.service import history
from app.core.workflow import delegation
from app.core.workflow.models import Workflow
from tests.support import move, open_case

pytestmark = pytest.mark.anyio


def _days(n: int) -> str:
    """The date n days from today, as the API expects it ("2026-10-19")."""
    return (delegation.today() + timedelta(days=n)).isoformat()


async def _delegate(act, user, from_position, to_position, start=0, end=6, **extra):
    body = {
        "from_position": from_position,
        "to_position": to_position,
        "starts_on": _days(start),
        "ends_on": _days(end),
        **extra,
    }
    return await act(user, "post", "/delegations", json=body)


async def _case_with_director(act, people) -> int:
    case = await open_case(act, people["applicant"])
    await move(act, people["records_officer"], case["id"], "with_minister")
    await move(act, people["minister"], case["id"], "with_ps")
    await move(act, people["permanent_secretary"], case["id"], "with_director")
    return case["id"]


async def test_delegate_can_act_and_the_audit_log_says_on_whose_behalf(act, people):
    case_id = await _case_with_director(act, people)
    officer, director = people["officer"], people["director"]
    assert (await move(act, officer, case_id, "with_officer")).status_code == 403

    created = await _delegate(
        act, director, "director_of_industry", "industry_officer",
        workflow="etls_application", reason="Annual leave",
    )
    assert created.status_code == 201, created.text
    delegation_id = created.json()["id"]

    # The officer now sees the Director's move, labelled as done for the Director.
    as_officer = (await act(officer, "get", f"/cases/{case_id}")).json()
    assert as_officer["available_actions"] == [
        {
            "to_status": "with_officer",
            "name": "Sign and assign to an officer",
            "on_behalf_of": "director_of_industry",
            "requires_comment": False,
            "blocked_by": [],
        }
    ]

    response = await move(act, officer, case_id, "with_officer", comment="Director on leave")
    assert response.status_code == 200, response.text

    last = (await act(director, "get", f"/cases/{case_id}/history")).json()[-1]
    assert last["actor_user_id"] == officer.id
    assert last["details"]["as_position"] == "industry_officer"
    assert last["details"]["on_behalf_of"] == "director_of_industry"
    assert last["details"]["delegation_id"] == delegation_id


async def test_the_delegating_post_keeps_its_own_powers(act, people):
    case_id = await _case_with_director(act, people)
    await _delegate(act, people["director"], "director_of_industry", "industry_officer")

    assert (await move(act, people["director"], case_id, "with_officer")).status_code == 200
    last = (await act(people["director"], "get", f"/cases/{case_id}/history")).json()[-1]
    assert last["details"]["as_position"] == "director_of_industry"
    assert last["details"]["on_behalf_of"] is None


async def test_a_delegation_only_works_between_its_dates(act, people, monkeypatch):
    case_id = await _case_with_director(act, people)
    real_today = delegation.today()
    created = await _delegate(act, people["director"], "director_of_industry", "industry_officer", start=1, end=2)
    assert created.status_code == 201

    def on(day_offset):
        monkeypatch.setattr(delegation, "today", lambda: real_today + timedelta(days=day_offset))

    officer = people["officer"]
    on(0)  # the day before it starts
    assert (await move(act, officer, case_id, "with_officer")).status_code == 403
    on(3)  # the day after it ends
    assert (await move(act, officer, case_id, "with_officer")).status_code == 403
    on(2)  # its last day: both dates are included
    assert (await move(act, officer, case_id, "with_officer")).status_code == 200


async def test_a_revoked_delegation_stops_working(act, people, make_user, db_session):
    case_id = await _case_with_director(act, people)
    director, officer = people["director"], people["officer"]
    delegation_id = (await _delegate(act, director, "director_of_industry", "industry_officer")).json()["id"]

    # Only the delegating post may revoke; others can't even see it exists.
    assert (await act(officer, "post", f"/delegations/{delegation_id}/revoke")).status_code == 403
    stranger = await make_user("officer", positions=["records_officer"])
    assert (await act(stranger, "post", f"/delegations/{delegation_id}/revoke")).status_code == 404

    revoked = await act(director, "post", f"/delegations/{delegation_id}/revoke")
    assert revoked.status_code == 200
    assert revoked.json()["revoked_at"] is not None
    assert (await act(director, "post", f"/delegations/{delegation_id}/revoke")).status_code == 409

    assert (await move(act, officer, case_id, "with_officer")).status_code == 403
    events = await history(db_session, "delegation", delegation_id)
    assert [(e.action, e.actor_user_id) for e in events] == [
        ("delegation.created", director.id),
        ("delegation.revoked", director.id),
    ]


async def test_delegations_are_not_passed_on(act, people):
    # Director -> Trade Officer, and Trade Officer -> Records Officer. The
    # Records Officer may act for the Trade Officer, but not for the Director.
    case_id = await _case_with_director(act, people)
    await _delegate(act, people["director"], "director_of_industry", "industry_officer")
    await _delegate(act, people["officer"], "industry_officer", "records_officer")

    assert (await move(act, people["records_officer"], case_id, "with_officer")).status_code == 403


async def test_a_delegation_for_one_workflow_does_not_cover_others(db_session, act, people):
    etls_id = await db_session.scalar(select(Workflow.id).where(Workflow.code == "etls_application"))
    other_id = etls_id + 1000  # stands in for a future workflow
    officer = people["officer"]

    await _delegate(act, people["director"], "director_of_industry", "industry_officer", workflow="etls_application")
    assert set(await delegation.active_delegations_to(db_session, officer, etls_id)) == {
        people["director"].positions[0].id
    }
    assert await delegation.active_delegations_to(db_session, officer, other_id) == {}

    # No workflow given: it covers every workflow.
    await _delegate(act, people["minister"], "minister", "industry_officer")
    assert len(await delegation.active_delegations_to(db_session, officer, other_id)) == 1


async def test_both_sides_see_the_delegation_and_others_dont(act, people):
    await _delegate(act, people["director"], "director_of_industry", "industry_officer", reason="Leave")

    for who in ("director", "officer"):
        listed = (await act(people[who], "get", "/delegations")).json()
        assert [(d["from_position"], d["to_position"], d["reason"]) for d in listed] == [
            ("director_of_industry", "industry_officer", "Leave")
        ]
    assert (await act(people["records_officer"], "get", "/delegations")).json() == []


@pytest.mark.parametrize(
    "who, changes, expected",
    [
        ("officer", {}, 403),  # doesn't hold the Director's post
        ("applicant", {}, 403),
        ("director", {"to_position": "director_of_industry"}, 422),  # to itself
        ("director", {"start": -1}, 422),  # starts in the past
        ("director", {"start": 3, "end": 2}, 422),  # ends before it starts
        ("director", {"end": delegation.MAX_DELEGATION_DAYS}, 422),  # one day too long
        ("director", {"to_position": "king"}, 404),
        ("director", {"workflow": "nope"}, 404),
    ],
    ids=["not-holder", "applicant", "to-self", "past", "backwards", "too-long", "unknown-post", "unknown-workflow"],
)
async def test_invalid_delegations_are_refused(act, people, who, changes, expected):
    changes = dict(changes)  # pytest reuses the dict; don't change it
    to_position = changes.pop("to_position", "industry_officer")
    response = await _delegate(act, people[who], "director_of_industry", to_position, **changes)
    assert response.status_code == expected, response.text


async def test_longest_allowed_delegation_is_accepted(act, people):
    end = delegation.MAX_DELEGATION_DAYS - 1  # today plus 89 more days = 90 days
    response = await _delegate(act, people["director"], "director_of_industry", "industry_officer", end=end)
    assert response.status_code == 201, response.text
