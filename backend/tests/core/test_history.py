"""Case history for screens: staff see it newest first with names, post titles and
"acting for"; applicants see a timeline of plain labels and dates."""

from datetime import timedelta

import pytest
from sqlalchemy import text

from app.core.workflow.delegation import today
from tests.support import confirm_hs_code, facility_letter_form, move, open_case, ready_for_records

pytestmark = pytest.mark.anyio


async def _title(db_session, code) -> str:
    return await db_session.scalar(text("SELECT title FROM core.positions WHERE code = :c"), {"c": code})


async def _letter_at_ps(act, people, number="CO-H-1") -> int:
    response = await act(
        people["applicant"], "post", "/etls/facility-letters",
        json=facility_letter_form(certificate_of_origin_numbers=[number]),
    )
    case_id = response.json()["case_id"]
    await ready_for_records(act, people, case_id)
    assert (await move(act, people["records_officer"], case_id, "originals_received")).status_code == 200
    assert (await confirm_hs_code(act, people, case_id)).status_code == 200
    assert (await move(act, people["desk"], case_id, "verified")).status_code == 200
    return case_id


async def _history(act, people, case_id) -> list[dict]:
    response = await act(people["desk"], "get", f"/cases/{case_id}/history")
    assert response.status_code == 200, response.text
    return response.json()


async def _signing(act, people, case_id) -> dict:
    # Signing also writes "case.document_issued" just after, so find the move itself.
    history = await _history(act, people, case_id)
    return next(e for e in history if e["action"] == "case.status_changed" and e["details"]["to"] == "signed")


async def _timeline(act, user, case_id) -> list[str]:
    response = await act(user, "get", f"/cases/{case_id}/timeline")
    assert response.status_code == 200, response.text
    return [e["label"] for e in response.json()]


# --- Staff history -----------------------------------------------------------


async def test_newest_first_with_names_and_post_titles(act, people, db_session):
    case_id = await _letter_at_ps(act, people)
    history = await _history(act, people, case_id)

    assert history[0]["action"] == "case.status_changed"
    assert history[0]["details"]["to"] == "verified"
    assert history[0]["actor_name"] == people["desk"].full_name
    assert history[0]["actor_title"] == await _title(db_session, "etls_desk_officer")
    assert history[0]["acting_for"] is None  # the desk's own step
    assert history[-1]["action"] == "case.created"
    assert history[-1]["actor_name"] == people["applicant"].full_name
    times = [e["occurred_at"] for e in history]
    assert times == sorted(times, reverse=True)


async def test_acting_by_succession_shows_whose_absence_and_the_dates(act, people, db_session):
    case_id = await _letter_at_ps(act, people)
    start, end = today(), today() + timedelta(days=4)
    away = await act(
        people["permanent_secretary"], "post", "/absences",
        json={"starts_on": start.isoformat(), "ends_on": end.isoformat()},
    )
    assert away.status_code == 201
    assert (await move(act, people["dps"], case_id, "signed")).status_code == 200

    signing = await _signing(act, people, case_id)
    assert signing["actor_name"] == people["dps"].full_name
    assert signing["actor_title"] == await _title(db_session, "dps_admin_finance")
    assert signing["acting_for"] == {
        "position": "permanent_secretary",
        "title": "Permanent Secretary",
        "basis": "succession",
        "absences": [
            {"person": people["permanent_secretary"].full_name, "starts_on": start.isoformat(), "ends_on": end.isoformat()}
        ],
        "delegation": None,
    }


async def test_acting_by_delegation_shows_the_delegation_and_its_dates(act, people, db_session):
    case_id = await _letter_at_ps(act, people, "CO-H-DEL")
    start, end = today(), today() + timedelta(days=2)
    delegation = await act(
        people["permanent_secretary"], "post", "/delegations",
        json={
            "from_position": "permanent_secretary",
            "to_position": "dps_admin_finance",
            "starts_on": start.isoformat(),
            "ends_on": end.isoformat(),
        },
    )
    assert delegation.status_code == 201, delegation.text
    assert (await move(act, people["dps"], case_id, "signed")).status_code == 200

    acting_for = (await _signing(act, people, case_id))["acting_for"]
    assert acting_for["basis"] == "delegation"
    assert acting_for["absences"] == []
    assert acting_for["delegation"] == {
        "from_position": "Permanent Secretary",
        "to_position": await _title(db_session, "dps_admin_finance"),
        "starts_on": start.isoformat(),
        "ends_on": end.isoformat(),
    }


# --- Applicant timeline ------------------------------------------------------


async def test_the_applicant_timeline_uses_plain_labels(act, people):
    case_id = await _letter_at_ps(act, people)
    assert (await move(act, people["permanent_secretary"], case_id, "signed")).status_code == 200

    response = await act(people["applicant"], "get", f"/cases/{case_id}/timeline")
    entries = response.json()
    assert [e["label"] for e in entries] == [
        "Draft",
        "Submitted",
        "Originals checked",
        "Awaiting signature",
        "Letter signed",
    ]
    # Labels and dates only: no names, posts, comments or internal step names.
    assert all(set(e) == {"occurred_at", "label"} for e in entries)


async def test_cancelling_a_letter_is_invisible_to_the_applicant(act, people):
    case_id = await _letter_at_ps(act, people, "CO-H-CAN")
    assert (await move(act, people["permanent_secretary"], case_id, "signed")).status_code == 200
    cancel = await move(act, people["permanent_secretary"], case_id, "originals_received", comment="Wrong date")
    assert cancel.status_code == 200

    assert (await _timeline(act, people["applicant"], case_id))[-1] == "Letter signed"  # no "cancelled" entry
    status = (await act(people["applicant"], "get", f"/cases/{case_id}")).json()["status"]
    assert status["label"] == "Being verified"


async def test_repeated_labels_are_shown_once(act, people):
    # Records, the Minister and the PS all move the approval file along, but to
    # the applicant each step reads "Accepted by the Ministry".
    case_id = (await open_case(act, people["applicant"]))["id"]
    for who, to_status in [
        ("records_officer", "with_minister"),
        ("minister", "with_ps"),
        ("permanent_secretary", "with_director"),
    ]:
        assert (await move(act, people[who], case_id, to_status)).status_code == 200
    assert await _timeline(act, people["applicant"], case_id) == ["Submitted", "Accepted by the Ministry"]


async def test_only_people_who_can_see_the_case_get_its_timeline(act, people, make_user):
    case_id = (await open_case(act, people["applicant"]))["id"]
    stranger = await make_user("applicant")
    assert (await act(stranger, "get", f"/cases/{case_id}/timeline")).status_code == 404
    assert (await act(people["desk"], "get", f"/cases/{case_id}/timeline")).status_code == 200
    assert (await act(people["applicant"], "get", f"/cases/{case_id}/history")).status_code == 403
