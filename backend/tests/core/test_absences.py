"""Recording, listing and cancelling absences.

What absences *do* (succession) is tested in test_acting_for.py.
"""

from datetime import timedelta

import pytest

from app.core.audit.service import history
from app.core.workflow import delegation

pytestmark = pytest.mark.anyio


def _days(n: int) -> str:
    return (delegation.today() + timedelta(days=n)).isoformat()


async def _record(act, actor, user=None, start=0, end=4, **extra):
    body = {"starts_on": _days(start), "ends_on": _days(end), **extra}
    if user is not None:
        body["user_id"] = user.id
    return await act(actor, "post", "/absences", json=body)


@pytest.fixture
async def recorder(make_user):
    """[CONFIRM] placeholder for "an authorised officer", e.g. the Minister's private secretary."""
    return await make_user("officer", "absence_recorder")


async def test_holder_records_their_own_absence(act, people, db_session):
    response = await _record(act, people["minister"], reason="ECOWAS summit")
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["user_id"] == body["recorded_by"] == people["minister"].id

    [event] = await history(db_session, "absence", body["id"])
    assert event.action == "absence.recorded"
    assert event.actor_user_id == people["minister"].id
    assert event.details["on_behalf"] is False
    assert event.details["positions"] == ["minister"]


async def test_authorised_officer_records_an_absence_on_someones_behalf(act, people, recorder, db_session):
    response = await _record(act, recorder, user=people["minister"])
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["user_id"] == people["minister"].id
    assert body["recorded_by"] == recorder.id

    # Audited as "recorded by": the actor is the recorder, not the absent Minister.
    [event] = await history(db_session, "absence", body["id"])
    assert event.actor_user_id == recorder.id
    assert event.details["absent_user_id"] == people["minister"].id
    assert event.details["recorded_by"] == recorder.id
    assert event.details["on_behalf"] is True


async def test_others_cannot_mark_someone_absent(act, people):
    # The PS would gain the Minister's step by marking the Minister absent.
    response = await _record(act, people["permanent_secretary"], user=people["minister"])
    assert response.status_code == 403


@pytest.mark.parametrize(
    "changes, expected",
    [
        ({"start": -1}, 422),  # back-dated
        ({"start": 3, "end": 2}, 422),  # ends before it starts
    ],
    ids=["past", "backwards"],
)
async def test_invalid_absences_are_refused(act, people, changes, expected):
    response = await _record(act, people["minister"], **changes)
    assert response.status_code == expected, response.text


async def test_only_post_holders_can_be_marked_absent(act, people, recorder):
    assert (await _record(act, people["applicant"])).status_code == 422
    assert (await _record(act, recorder, user=people["applicant"])).status_code == 422


async def test_unknown_user_is_404(act, recorder):
    assert (await _record(act, recorder, user_id=999_999)).status_code == 404


async def test_cancelling_an_absence(act, people, recorder, db_session):
    absence_id = (await _record(act, people["minister"])).json()["id"]

    assert (await act(people["permanent_secretary"], "post", f"/absences/{absence_id}/cancel")).status_code == 404
    response = await act(people["minister"], "post", f"/absences/{absence_id}/cancel")
    assert response.status_code == 200
    assert response.json()["cancelled_at"] is not None
    assert (await act(recorder, "post", f"/absences/{absence_id}/cancel")).status_code == 409

    events = await history(db_session, "absence", absence_id)
    assert [e.action for e in events] == ["absence.recorded", "absence.cancelled"]


async def test_a_recorder_can_cancel_for_someone(act, people, recorder):
    absence_id = (await _record(act, recorder, user=people["director"])).json()["id"]
    assert (await act(recorder, "post", f"/absences/{absence_id}/cancel")).status_code == 200


async def test_who_sees_which_absences(act, people, recorder):
    await _record(act, people["minister"])
    await _record(act, recorder, user=people["director"])

    own = (await act(people["minister"], "get", "/absences")).json()
    assert [a["user_id"] for a in own] == [people["minister"].id]
    everyone = (await act(recorder, "get", "/absences")).json()
    assert {a["user_id"] for a in everyone} >= {people["minister"].id, people["director"].id}
    assert (await act(people["officer"], "get", "/absences")).json() == []
