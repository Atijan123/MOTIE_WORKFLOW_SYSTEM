"""The workflow engine, tested through the HTTP API with the seeded ETLS workflow."""

import pytest

pytestmark = pytest.mark.anyio


@pytest.fixture
async def people(make_user):
    """One user per role in the ETLS chain."""
    return {
        role: await make_user(role)
        for role in (
            "applicant",
            "records_officer",
            "minister",
            "permanent_secretary",
            "director",
            "officer",
        )
    }


@pytest.fixture
def act(client, auth_headers):
    """Shortcut: `await act(user, "post", "/cases/1/status", json=...)`."""

    async def _act(user, method, url, **kwargs):
        return await getattr(client, method)(url, headers=auth_headers(user), **kwargs)

    return _act


async def _open_case(act, applicant) -> dict:
    response = await act(applicant, "post", "/cases", json={"workflow": "etls_application"})
    assert response.status_code == 201, response.text
    return response.json()


async def _move(act, user, case_id, to_status, comment=None):
    return await act(
        user, "post", f"/cases/{case_id}/status", json={"to_status": to_status, "comment": comment}
    )


async def test_case_walks_the_whole_chain_and_every_step_is_audited(act, people):
    case = await _open_case(act, people["applicant"])
    assert case["status"]["code"] == "submitted"
    assert case["available_actions"] == []  # applicants can't move their own case

    steps = [
        ("records_officer", "with_minister"),
        ("minister", "with_directorate"),
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
    assert [e["action"] for e in history] == ["case.created"] + ["case.status_changed"] * 4
    assert [e["actor_user_id"] for e in history] == [
        people[r].id for r in ("applicant", "records_officer", "minister", "director", "officer")
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


async def test_permanent_secretary_can_act_for_the_minister(act, people):
    case = await _open_case(act, people["applicant"])
    await _move(act, people["records_officer"], case["id"], "with_minister")

    response = await _move(act, people["permanent_secretary"], case["id"], "with_directorate")

    assert response.status_code == 200
    assert response.json()["status"]["code"] == "with_directorate"


async def test_officer_can_return_a_case_to_the_directorate(act, people):
    case = await _open_case(act, people["applicant"])
    for role, to_status in [
        ("records_officer", "with_minister"),
        ("minister", "with_directorate"),
        ("director", "with_officer"),
        ("officer", "with_directorate"),
    ]:
        assert (await _move(act, people[role], case["id"], to_status)).status_code == 200


async def test_final_status_cannot_be_left(act, people):
    case = await _open_case(act, people["applicant"])
    for role, to_status in [
        ("records_officer", "with_minister"),
        ("minister", "with_directorate"),
        ("director", "with_officer"),
        ("officer", "rejected"),
    ]:
        await _move(act, people[role], case["id"], to_status)

    response = await _move(act, people["officer"], case["id"], "with_directorate")
    assert response.status_code == 409


async def test_available_actions_depend_on_who_is_asking(act, people):
    case = await _open_case(act, people["applicant"])

    as_records = (await act(people["records_officer"], "get", f"/cases/{case['id']}")).json()
    as_officer = (await act(people["officer"], "get", f"/cases/{case['id']}")).json()

    assert as_records["available_actions"] == [
        {"to_status": "with_minister", "name": "Register and forward to the Minister"}
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
