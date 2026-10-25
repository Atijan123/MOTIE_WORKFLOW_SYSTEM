"""Records sends signed letters to GRA (SCREENS.md S1 "Outgoing", C9); "Sent to GRA"
is final; and a corrected letter shows as such on the applicant's timeline (C11)."""

from datetime import timedelta

import pytest
from sqlalchemy import func, select

from app.core.workflow.delegation import today
from app.modules.etls.models import FacilityLetterDispatch
from tests.support import (
    create_draft,
    move,
    ready_for_records,
    ready_to_verify,
    send_to_gra,
)

pytestmark = pytest.mark.anyio


async def _signed(act, people, number="CO-GRA-1") -> int:
    case_id = await create_draft(act, people["applicant"], certificate_of_origin_numbers=[number])
    await ready_for_records(act, people, case_id)
    assert (await move(act, people["records_officer"], case_id, "originals_received")).status_code == 200
    await _verify_and_sign(act, people, case_id)
    return case_id


async def _verify_and_sign(act, people, case_id):
    assert (await ready_to_verify(act, people, case_id)).status_code == 200
    assert (await move(act, people["desk"], case_id, "verified")).status_code == 200
    assert (await move(act, people["permanent_secretary"], case_id, "signed")).status_code == 200


async def _queue(act, user, **params) -> list[int]:
    return [row["id"] for row in (await act(user, "get", "/cases/queue", params=params)).json()]


async def _timeline(act, people, case_id) -> list[str]:
    return [e["label"] for e in (await act(people["applicant"], "get", f"/cases/{case_id}/timeline")).json()]


async def test_signed_letters_wait_in_records_outgoing_tab_not_the_ps_queue(act, people):
    case_id = await _signed(act, people)
    assert case_id in await _queue(act, people["records_officer"], status="signed")
    # The PS could cancel it, but that's a correction, not work waiting for them.
    assert case_id not in await _queue(act, people["permanent_secretary"])
    assert case_id not in await _queue(act, people["desk"])


async def test_records_marks_it_sent_with_the_dispatch_date(act, people):
    case_id = await _signed(act, people)
    # The letter was signed today, so it can only have gone today.
    response = await send_to_gra(act, people, case_id, today())
    assert response.status_code == 200, response.text
    case = response.json()
    assert case["status"]["code"] == "sent_to_gra"
    assert case["status"]["is_final"] is True
    assert case["available_actions"] == []  # Records has nothing more to do; no "Close"

    [current] = (await act(people["desk"], "get", f"/etls/facility-letters/{case_id}/letters")).json()
    assert current["sent_to_gra_on"] == today().isoformat()
    history = (await act(people["desk"], "get", f"/cases/{case_id}/history")).json()
    [dispatched] = [e for e in history if e["action"] == "case.letter_dispatched"]
    assert dispatched["details"]["sha256"] == current["sha256"]
    assert case_id not in await _queue(act, people["records_officer"])


async def test_the_dispatch_date_is_needed_but_the_button_is_not_shown_blocked(act, people):
    case_id = await _signed(act, people)
    actions = (await act(people["records_officer"], "get", f"/cases/{case_id}")).json()["available_actions"]
    [send] = [a for a in actions if a["to_status"] == "sent_to_gra"]
    assert send["name"] == "Mark sent to GRA"
    assert send["blocked_by"] == []  # the date comes with the click

    # The generic endpoint can't make the move without a date.
    response = await move(act, people["records_officer"], case_id, "sent_to_gra")
    assert response.status_code == 409
    assert "dispatch date" in response.json()["detail"]


@pytest.mark.parametrize("days", [1, -1])
async def test_the_date_must_be_between_signing_and_today(act, people, days):
    case_id = await _signed(act, people)
    response = await send_to_gra(act, people, case_id, today() + timedelta(days=days))
    assert response.status_code == 422


async def test_only_records_sends_and_a_refusal_leaves_nothing_behind(act, people, db_session):
    case_id = await _signed(act, people)
    for who in ("desk", "permanent_secretary"):
        assert (await send_to_gra(act, people, case_id, who=who)).status_code == 403, who
    assert (await send_to_gra(act, people, case_id)).status_code == 200
    # Only Records' dispatch was saved; the refused attempts were rolled back.
    count = await db_session.scalar(
        select(func.count()).select_from(FacilityLetterDispatch).where(FacilityLetterDispatch.case_id == case_id)
    )
    assert count == 1


async def test_a_corrected_letter_after_gra_had_one_reads_corrected_letter_issued(act, people):
    case_id = await _signed(act, people, "CO-GRA-CORR")
    assert (await send_to_gra(act, people, case_id)).status_code == 200
    cancel = await move(act, people["permanent_secretary"], case_id, "originals_received", comment="Wrong quantity")
    assert cancel.status_code == 200, cancel.text
    await _verify_and_sign(act, people, case_id)
    # The corrected letter is a new issued letter, so it needs its own dispatch.
    assert (await send_to_gra(act, people, case_id)).status_code == 200

    assert await _timeline(act, people, case_id) == [
        "Draft",
        "Submitted",
        "Originals checked",
        "Awaiting signature",
        "Letter signed",
        "Letter sent to GRA",
        # the cancel itself is hidden
        "Awaiting signature",
        "Letter signed",
        "Corrected letter issued",
    ]
    letters = (await act(people["desk"], "get", f"/etls/facility-letters/{case_id}/letters")).json()
    assert [(l["status"], l["sent_to_gra_on"] is not None) for l in letters] == [("cancelled", True), ("current", True)]


async def test_a_letter_cancelled_before_it_was_sent_reads_normally(act, people):
    case_id = await _signed(act, people, "CO-GRA-EARLY")
    cancel = await move(act, people["permanent_secretary"], case_id, "originals_received", comment="Typo")
    assert cancel.status_code == 200, cancel.text
    await _verify_and_sign(act, people, case_id)
    assert (await send_to_gra(act, people, case_id)).status_code == 200
    assert (await _timeline(act, people, case_id))[-1] == "Letter sent to GRA"


async def test_the_download_is_named_after_the_case_reference(act, people):
    case_id = await _signed(act, people, "CO-GRA-NAME")
    reference = (await act(people["desk"], "get", f"/cases/{case_id}")).json()["reference"]
    [current] = (await act(people["desk"], "get", f"/etls/facility-letters/{case_id}/letters")).json()
    assert current["filename"] == "facility-letter-" + reference.replace("/", "-") + ".pdf"
