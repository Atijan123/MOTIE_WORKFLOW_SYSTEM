"""The workflow engine, tested through the HTTP API with the seeded ETLS workflow."""

from datetime import timedelta

import pytest

from app.core.identity.service import assign_position, remove_position
from app.core.workflow.delegation import today
from tests.support import move as _move
from tests.support import open_case as _open_case

pytestmark = pytest.mark.anyio

# Fixtures `people` and `act` live in tests/conftest.py.


async def test_case_walks_the_whole_chain_and_every_step_is_audited(act, people):
    case = await _open_case(act, people["applicant"])
    assert case["status"]["label"] == "Submitted"  # the applicant sees the label only
    assert case["available_actions"] == []  # applicants can't move their own case

    steps = [
        ("records_officer", "with_minister"),
        ("minister", "with_ps"),
        ("permanent_secretary", "with_director"),
        ("director", "with_officer"),
        ("officer", "approved"),
    ]
    for role, to_status in steps:
        response = await _move(act, people[role], case["id"], to_status, comment=f"by {role}")
        assert response.status_code == 200, response.text
        assert response.json()["status"]["code"] == to_status

    final = response.json()
    assert final["status"]["is_final"] is True
    assert final["available_actions"] == []

    history = (await act(people["director"], "get", f"/cases/{case['id']}/history")).json()
    assert [e["action"] for e in history] == ["case.created"] + ["case.status_changed"] * 5
    assert [e["actor_user_id"] for e in history] == [
        people[r].id
        for r in ("applicant", "records_officer", "minister", "permanent_secretary", "director", "officer")
    ]
    assert history[1]["details"]["from"] == "submitted"
    assert history[1]["details"]["to"] == "with_minister"
    assert history[1]["details"]["comment"] == "by records_officer"


async def test_skipping_a_step_is_refused_and_nothing_is_recorded(act, people):
    case = await _open_case(act, people["applicant"])

    response = await _move(act, people["officer"], case["id"], "approved")

    assert response.status_code == 409
    after = (await act(people["director"], "get", f"/cases/{case['id']}")).json()
    assert after["status"]["code"] == "submitted"
    history = (await act(people["director"], "get", f"/cases/{case['id']}/history")).json()
    assert len(history) == 1  # only the creation


async def test_the_right_move_by_the_wrong_role_is_forbidden(act, people):
    case = await _open_case(act, people["applicant"])
    for role in ("applicant", "director", "minister"):
        response = await _move(act, people[role], case["id"], "with_minister")
        assert response.status_code == 403, role


async def _minister_is_away(act, people):
    """The Minister delegates their post to the PS for the coming week."""
    response = await act(
        people["minister"],
        "post",
        "/delegations",
        json={
            "from_position": "minister",
            "to_position": "permanent_secretary",
            "starts_on": today().isoformat(),
            "ends_on": (today() + timedelta(days=6)).isoformat(),
            "reason": "Travelling",
        },
    )
    assert response.status_code == 201, response.text


async def test_permanent_secretary_can_act_for_the_minister(act, people):
    # Since step 4e this works through real delegation, not a standing rule.
    case = await _open_case(act, people["applicant"])
    await _move(act, people["records_officer"], case["id"], "with_minister")
    await _minister_is_away(act, people)

    response = await _move(act, people["permanent_secretary"], case["id"], "with_ps")

    assert response.status_code == 200
    assert response.json()["status"]["code"] == "with_ps"
    history = (await act(people["director"], "get", f"/cases/{case['id']}/history")).json()
    assert history[-1]["actor_user_id"] == people["permanent_secretary"].id
    assert history[-1]["details"]["as_position"] == "permanent_secretary"
    assert history[-1]["details"]["on_behalf_of"] == "minister"


async def test_permanent_secretary_cannot_act_for_the_minister_without_a_delegation(act, people):
    case = await _open_case(act, people["applicant"])
    await _move(act, people["records_officer"], case["id"], "with_minister")

    as_ps = (await act(people["permanent_secretary"], "get", f"/cases/{case['id']}")).json()
    assert as_ps["available_actions"] == []
    response = await _move(act, people["permanent_secretary"], case["id"], "with_ps")
    assert response.status_code == 403


async def test_the_position_decides_not_the_role(act, people, make_user):
    case = await _open_case(act, people["applicant"])
    # Has the records_officer role but holds no post: not allowed.
    no_post = await make_user("records_officer")
    # Holds the Records Officer post (e.g. a clerk covering the Registry): allowed.
    clerk = await make_user("officer", positions=["records_officer"])

    assert (await _move(act, no_post, case["id"], "with_minister")).status_code == 403
    response = await _move(act, clerk, case["id"], "with_minister")
    assert response.status_code == 200

    history = (await act(people["director"], "get", f"/cases/{case['id']}/history")).json()
    assert history[-1]["details"]["as_position"] == "records_officer"


async def test_a_new_post_holder_takes_over_at_once(act, people, make_user, db_session):
    case = await _open_case(act, people["applicant"])
    await _move(act, people["records_officer"], case["id"], "with_minister")
    await _move(act, people["minister"], case["id"], "with_ps")
    await _move(act, people["permanent_secretary"], case["id"], "with_director")

    old_director = people["director"]
    new_director = await make_user("director")
    await remove_position(db_session, user=old_director, position_code="director_of_industry", actor=None)
    await assign_position(db_session, user=new_director, position_code="director_of_industry", actor=None)

    # No workflow row changed: the move names the post, and the post changed hands.
    assert (await _move(act, old_director, case["id"], "with_officer")).status_code == 403
    assert (await _move(act, new_director, case["id"], "with_officer")).status_code == 200


async def test_officer_can_return_a_case_to_the_director(act, people):
    case = await _open_case(act, people["applicant"])
    for role, to_status in [
        ("records_officer", "with_minister"),
        ("minister", "with_ps"),
        ("permanent_secretary", "with_director"),
        ("director", "with_officer"),
        ("officer", "with_director"),
    ]:
        assert (await _move(act, people[role], case["id"], to_status)).status_code == 200


async def test_final_status_cannot_be_left(act, people):
    case = await _open_case(act, people["applicant"])
    for role, to_status in [
        ("records_officer", "with_minister"),
        ("minister", "with_ps"),
        ("permanent_secretary", "with_director"),
        ("director", "with_officer"),
        ("officer", "rejected"),
    ]:
        await _move(act, people[role], case["id"], to_status)

    response = await _move(act, people["officer"], case["id"], "with_director")
    assert response.status_code == 409


async def test_available_actions_depend_on_who_is_asking(act, people):
    case = await _open_case(act, people["applicant"])

    as_records = (await act(people["records_officer"], "get", f"/cases/{case['id']}")).json()
    as_officer = (await act(people["officer"], "get", f"/cases/{case['id']}")).json()

    assert as_records["available_actions"] == [
        {
            "to_status": "with_minister",
            "name": "Register and forward to the Minister",
            "on_behalf_of": None,
            "requires_comment": False,
            "blocked_by": [],
        }
    ]
    assert as_officer["available_actions"] == []


async def test_applicants_only_see_their_own_cases(act, people, make_user):
    case = await _open_case(act, people["applicant"])
    other_applicant = await make_user("applicant")

    theirs = await act(other_applicant, "get", f"/cases/{case['id']}")
    missing = await act(other_applicant, "get", "/cases/999999")

    # Someone else's case looks exactly like a case that doesn't exist.
    assert theirs.status_code == missing.status_code == 404
    assert theirs.json() == missing.json()
    assert (await act(people["applicant"], "get", f"/cases/{case['id']}")).status_code == 200
    assert (await act(people["officer"], "get", f"/cases/{case['id']}")).status_code == 200


async def test_applicants_cannot_read_internal_history(act, people):
    case = await _open_case(act, people["applicant"])
    response = await act(people["applicant"], "get", f"/cases/{case['id']}/history")
    assert response.status_code == 403


async def test_only_the_start_role_can_open_a_case(act, people):
    response = await act(people["officer"], "post", "/cases", json={"workflow": "etls_application"})
    assert response.status_code == 403


async def test_unknown_workflow_is_404(act, people):
    response = await act(people["applicant"], "post", "/cases", json={"workflow": "nope"})
    assert response.status_code == 404


async def test_cases_require_login(client):
    assert (await client.get("/cases/1")).status_code == 401
    assert (await client.post("/cases", json={"workflow": "etls_application"})).status_code == 401
