"""Lists and queues: my applications, and each staff member's queue of cases to act on.

Other tests commit cases of their own (race tests), so these tests look for
their own case ids in a queue rather than comparing whole queues.
"""

from datetime import timedelta

import pytest
from sqlalchemy import text

from app.core.workflow.delegation import today
from tests.support import confirm_hs_code, create_draft, move, ready_for_records, submitted_case

pytestmark = pytest.mark.anyio


async def _submit(act, people, number="CO-Q-1", **form) -> int:
    return await submitted_case(act, people, certificate_of_origin_numbers=[number], **form)


async def _to_desk(act, people, case_id):
    await ready_for_records(act, people, case_id)
    assert (await move(act, people["records_officer"], case_id, "originals_received")).status_code == 200


async def _to_ps(act, people, case_id):
    await _to_desk(act, people, case_id)
    assert (await confirm_hs_code(act, people, case_id)).status_code == 200
    assert (await move(act, people["desk"], case_id, "verified")).status_code == 200


async def _queue(act, user, **params) -> dict[int, dict]:
    response = await act(user, "get", "/cases/queue", params=params)
    assert response.status_code == 200, response.text
    return {item["id"]: item for item in response.json()}


# --- My applications ---------------------------------------------------------


async def test_an_applicant_lists_their_own_cases_newest_first(act, people, make_user):
    first = await _submit(act, people, "CO-Q-A")
    second = await _submit(act, people, "CO-Q-B")
    other = await make_user("applicant")
    await create_draft(act, other, certificate_of_origin_numbers=["CO-Q-X"])

    response = await act(people["applicant"], "get", "/cases")
    assert response.status_code == 200
    mine = response.json()
    assert [c["id"] for c in mine] == [second, first]  # nobody else's
    row = mine[0]
    assert row["reference"].startswith("MOTIE/ETLS/FL/")
    assert row["service"] == "ETLS facility letter (imports)"
    assert row["summary"] == "Roofing sheets, 1200.5 tonnes"
    assert row["status"]["label"] == "Submitted"
    assert row["status"]["code"] is None  # applicants never see internal names
    assert row["applicant_name"] is None
    assert row["available_actions"] == []


# --- Staff queues ------------------------------------------------------------


async def test_the_queue_follows_the_case_from_records_to_the_desk(act, people):
    case_id = await _submit(act, people)

    records = await _queue(act, people["records_officer"])
    assert case_id in records
    assert [a["name"] for a in records[case_id]["available_actions"]] == ["Confirm originals received", "Return to applicant"]
    assert records[case_id]["applicant_name"] == people["applicant"].full_name
    assert records[case_id]["status"]["code"] == "submitted"
    assert case_id not in await _queue(act, people["desk"])

    await _to_desk(act, people, case_id)
    assert case_id not in await _queue(act, people["records_officer"])
    assert case_id in await _queue(act, people["desk"])


async def test_longest_waiting_first_with_days_waiting(act, people, db_session):
    newer = await _submit(act, people, "CO-Q-NEW")
    older = await _submit(act, people, "CO-Q-OLD")
    # Everything in one test happens in one transaction, at one now(); age one case by hand.
    await db_session.execute(
        text("UPDATE core.cases SET status_changed_at = now() - interval '5 days' WHERE id = :id"), {"id": older}
    )

    queue = await _queue(act, people["records_officer"])
    ids = [i for i in queue if i in (newer, older)]
    assert ids == [older, newer]
    assert queue[older]["days_waiting"] == 5
    assert queue[newer]["days_waiting"] == 0


async def test_someone_acting_by_succession_sees_the_absent_posts_cases(act, people):
    case_id = await _submit(act, people)
    await _to_ps(act, people, case_id)
    assert case_id in await _queue(act, people["permanent_secretary"])
    assert case_id not in await _queue(act, people["dps"])

    start, end = today().isoformat(), (today() + timedelta(days=2)).isoformat()
    away = await act(people["permanent_secretary"], "post", "/absences", json={"starts_on": start, "ends_on": end})
    assert away.status_code == 201

    dps = await _queue(act, people["dps"])
    assert case_id in dps
    [action] = [a for a in dps[case_id]["available_actions"] if a["to_status"] == "signed"]
    assert action["on_behalf_of"] == "permanent_secretary"


async def test_a_delegate_sees_the_delegating_posts_cases(act, people):
    case_id = await _submit(act, people)
    await _to_ps(act, people, case_id)
    delegation = await act(
        people["permanent_secretary"], "post", "/delegations",
        json={
            "from_position": "permanent_secretary",
            "to_position": "dps_admin_finance",
            "starts_on": today().isoformat(),
            "ends_on": (today() + timedelta(days=2)).isoformat(),
        },
    )
    assert delegation.status_code == 201, delegation.text
    assert case_id in await _queue(act, people["dps"])


async def test_the_queue_can_be_narrowed_to_one_status(act, people):
    waiting = await _submit(act, people, "CO-Q-W")
    await _to_desk(act, people, waiting)
    signed = await _submit(act, people, "CO-Q-S")
    await _to_ps(act, people, signed)
    assert (await move(act, people["permanent_secretary"], signed, "signed")).status_code == 200

    only_signed = await _queue(act, people["desk"], status="signed")
    assert signed in only_signed and waiting not in only_signed
    assert all(item["status"]["code"] == "signed" for item in only_signed.values())


async def test_finished_cases_leave_every_queue(act, people):
    case_id = await _submit(act, people)
    await _to_desk(act, people, case_id)
    assert (await move(act, people["desk"], case_id, "rejected", applicant_message="Not eligible")).status_code == 200
    for who in ("records_officer", "desk", "permanent_secretary"):
        assert case_id not in await _queue(act, people[who])


async def test_applicants_have_no_queue(act, people):
    assert (await act(people["applicant"], "get", "/cases/queue")).status_code == 403
