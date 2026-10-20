"""Acting for an absent post through the succession order.

Confirmed rules: general chain Minister -> PS -> DPS; for ETLS, the Director of
Industry and Investment is covered by the DPS Administration and Finance.
"""

from datetime import timedelta

import pytest

from app.core.identity.service import remove_position
from app.core.workflow import delegation
from tests.support import STAFF, move, open_case

pytestmark = pytest.mark.anyio

# The ETLS route: (whose step, the status it moves the case to).
ROUTE = [
    ("records_officer", "with_minister"),
    ("minister", "with_ps"),
    ("permanent_secretary", "with_director"),
    ("director", "with_officer"),
    ("officer", "approved"),
]


async def _away(act, person) -> int:
    """The person records their own absence, from today for a week."""
    today = delegation.today()
    response = await act(
        person,
        "post",
        "/absences",
        json={"starts_on": today.isoformat(), "ends_on": (today + timedelta(days=6)).isoformat()},
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


async def _case_ready_for(act, people, status) -> int:
    """A new case, moved along the route by each step's own post, up to (not
    including) the step that moves it to `status`."""
    case_id = (await open_case(act, people["applicant"]))["id"]
    for who, to_status in ROUTE:
        if to_status == status:
            break
        assert (await move(act, people[who], case_id, to_status)).status_code == 200
    else:
        raise AssertionError(f"{status} isn't on the route")
    return case_id


async def _last_event(act, people, case_id) -> dict:
    return (await act(people["records_officer"], "get", f"/cases/{case_id}/history")).json()[-1]


async def _actions(act, person, case_id) -> list[dict]:
    return (await act(person, "get", f"/cases/{case_id}")).json()["available_actions"]


async def test_minister_absent_ps_does_the_ministers_step(act, people):
    case_id = await _case_ready_for(act, people, "with_ps")  # with the Minister
    absence_id = await _away(act, people["minister"])

    assert await _actions(act, people["permanent_secretary"], case_id) == [
        {"to_status": "with_ps", "name": "Minute to the Permanent Secretary", "on_behalf_of": "minister", "requires_comment": False}
    ]
    # Only the first one in line who is present: the PS is, so the DPS may not.
    assert (await move(act, people["dps"], case_id, "with_ps")).status_code == 403
    assert (await move(act, people["permanent_secretary"], case_id, "with_ps")).status_code == 200

    details = (await _last_event(act, people, case_id))["details"]
    assert details["as_position"] == "permanent_secretary"
    assert details["on_behalf_of"] == "minister"
    assert details["basis"] == "succession"
    assert details["absence_ids"] == [absence_id]


async def test_minister_and_ps_both_absent_dps_does_the_ministers_step(act, people):
    case_id = await _case_ready_for(act, people, "with_ps")
    minister_away = await _away(act, people["minister"])
    ps_away = await _away(act, people["permanent_secretary"])

    assert (await move(act, people["permanent_secretary"], case_id, "with_ps")).status_code == 403
    response = await move(act, people["dps"], case_id, "with_ps")
    assert response.status_code == 200, response.text

    event = await _last_event(act, people, case_id)
    assert event["actor_user_id"] == people["dps"].id
    assert event["details"]["as_position"] == "dps_admin_finance"
    assert event["details"]["on_behalf_of"] == "minister"
    # Both absences explain why the DPS acted: the Minister's, and the PS's (skipped).
    assert event["details"]["absence_ids"] == [minister_away, ps_away]


async def test_director_absent_dps_admin_and_finance_signs_and_assigns(act, people):
    case_id = await _case_ready_for(act, people, "with_officer")  # with the Director
    absence_id = await _away(act, people["director"])

    response = await move(act, people["dps"], case_id, "with_officer", comment="Signed for the Director")
    assert response.status_code == 200, response.text
    assert response.json()["status"]["code"] == "with_officer"

    details = (await _last_event(act, people, case_id))["details"]
    assert details["transition"] == "Sign and assign to an officer"
    assert details["as_position"] == "dps_admin_finance"
    assert details["on_behalf_of"] == "director_of_industry"
    assert details["absence_ids"] == [absence_id]


async def test_director_present_dps_admin_and_finance_cannot_sign(act, people):
    case_id = await _case_ready_for(act, people, "with_officer")

    assert await _actions(act, people["dps"], case_id) == []
    assert (await move(act, people["dps"], case_id, "with_officer")).status_code == 403


async def test_nobody_absent_each_step_only_by_its_own_post(act, people):
    case_id = (await open_case(act, people["applicant"]))["id"]
    for owner, to_status in ROUTE:
        for other in STAFF:
            if other != owner:
                response = await move(act, people[other], case_id, to_status)
                assert response.status_code == 403, f"{other} made {owner}'s step"
        response = await move(act, people[owner], case_id, to_status)
        assert response.status_code == 200, f"{owner}: {response.text}"
        assert (await _last_event(act, people, case_id))["details"]["basis"] == "own"


async def test_case_history_shows_who_acted_for_whom(act, people):
    case_id = (await open_case(act, people["applicant"]))["id"]
    await _away(act, people["minister"])
    await _away(act, people["director"])

    for actor, to_status in [
        ("records_officer", "with_minister"),
        ("permanent_secretary", "with_ps"),  # for the Minister
        ("permanent_secretary", "with_director"),  # the PS's own step
        ("dps", "with_officer"),  # for the Director
        ("officer", "approved"),
    ]:
        assert (await move(act, people[actor], case_id, to_status)).status_code == 200, actor

    history = (await act(people["records_officer"], "get", f"/cases/{case_id}/history")).json()
    moves = [
        (e["actor_user_id"], e["details"]["as_position"], e["details"]["on_behalf_of"])
        for e in history
        if e["action"] == "case.status_changed"
    ]
    assert moves == [
        (people["records_officer"].id, "records_officer", None),
        (people["permanent_secretary"].id, "permanent_secretary", "minister"),
        (people["permanent_secretary"].id, "permanent_secretary", None),
        (people["dps"].id, "dps_admin_finance", "director_of_industry"),
        (people["officer"].id, "industry_officer", None),
    ]


async def test_a_personal_delegation_takes_priority_over_succession(act, people):
    case_id = await _case_ready_for(act, people, "with_ps")
    await _away(act, people["minister"])
    today = delegation.today()
    response = await act(
        people["minister"],
        "post",
        "/delegations",
        json={
            "from_position": "minister",
            "to_position": "dps_admin_finance",
            "starts_on": today.isoformat(),
            "ends_on": (today + timedelta(days=6)).isoformat(),
        },
    )
    assert response.status_code == 201, response.text

    # The Minister chose the DPS, so the PS (first in the standing order) may not.
    assert (await move(act, people["permanent_secretary"], case_id, "with_ps")).status_code == 403
    assert (await move(act, people["dps"], case_id, "with_ps")).status_code == 200
    details = (await _last_event(act, people, case_id))["details"]
    assert details["basis"] == "delegation"
    assert details["on_behalf_of"] == "minister"


async def test_an_absent_holder_can_still_act_in_their_own_right(act, people):
    case_id = await _case_ready_for(act, people, "with_ps")
    await _away(act, people["minister"])

    assert (await move(act, people["minister"], case_id, "with_ps")).status_code == 200
    assert (await _last_event(act, people, case_id))["details"]["basis"] == "own"


async def test_a_cancelled_absence_ends_the_cover(act, people):
    case_id = await _case_ready_for(act, people, "with_ps")
    absence_id = await _away(act, people["minister"])
    await act(people["minister"], "post", f"/absences/{absence_id}/cancel")

    assert (await move(act, people["permanent_secretary"], case_id, "with_ps")).status_code == 403


async def test_a_vacant_post_is_not_treated_as_absent(act, people, db_session):
    # [CONFIRM] placeholder rule: nobody acts for a post with no holder at all.
    case_id = await _case_ready_for(act, people, "with_ps")
    await remove_position(db_session, user=people["minister"], position_code="minister", actor=None)

    assert (await move(act, people["permanent_secretary"], case_id, "with_ps")).status_code == 403
