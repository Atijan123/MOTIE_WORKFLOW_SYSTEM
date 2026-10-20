"""The HS code on a facility letter: declared by the applicant, confirmed by an
officer, and driving the receipt rule (HS heading 2523 = cement)."""

import pytest
from sqlalchemy import select

from app.core.audit.models import AuditEvent
from tests.support import confirm_hs_code, facility_letter_form, move, ready_for_records, upload

pytestmark = pytest.mark.anyio


async def _submit(act, people, **form):
    return await act(people["applicant"], "post", "/etls/facility-letters", json=facility_letter_form(**form))


async def _at_desk(act, people, **form) -> int:
    """A case past Records, waiting for the desk to verify it."""
    case_id = (await _submit(act, people, **form)).json()["case_id"]
    await ready_for_records(act, people, case_id)
    assert (await move(act, people["records_officer"], case_id, "originals_received")).status_code == 200
    return case_id


async def _receipt_applies(act, people, case_id) -> bool:
    checklist = (await act(people["desk"], "get", f"/cases/{case_id}/documents")).json()
    return next(item for item in checklist if item["type"] == "cement_receipt")["applies"]


# --- The form ----------------------------------------------------------------


@pytest.mark.parametrize(
    "typed, stored", [("2523.29", "252329"), (" 7210 49 ", "721049"), ("2523.29.00", "25232900"), ("2523290000", "2523290000")]
)
async def test_the_hs_code_is_stored_as_digits(act, people, typed, stored):
    response = await _submit(act, people, hs_code=typed)
    assert response.status_code == 201, response.text
    assert response.json()["hs_code"] == stored
    assert response.json()["hs_code_confirmed"] is None


@pytest.mark.parametrize("bad", ["", "2523", "25232", "2523291", "2523-29", "25AB29", "２５２３２９"])
async def test_a_malformed_hs_code_is_refused(act, people, bad):
    assert (await _submit(act, people, hs_code=bad)).status_code == 422


def _form_without_hs_code(**changes) -> dict:
    form = facility_letter_form(**changes)
    del form["hs_code"]
    return form


async def test_the_applicant_may_leave_the_hs_code_out(act, people):
    response = await act(people["applicant"], "post", "/etls/facility-letters", json=_form_without_hs_code())
    assert response.status_code == 201, response.text
    assert response.json()["hs_code"] is None
    # Without a code, nobody can tell yet whether the cement receipt is needed.
    checklist = (await act(people["applicant"], "get", f"/cases/{response.json()['case_id']}/documents")).json()
    receipt = next(item for item in checklist if item["type"] == "cement_receipt")
    assert receipt["applies"] is None
    assert receipt["missing"] is False


async def _at_desk_without_code(act, people, **changes) -> int:
    response = await act(people["applicant"], "post", "/etls/facility-letters", json=_form_without_hs_code(**changes))
    case_id = response.json()["case_id"]
    await ready_for_records(act, people, case_id)  # skips the undecided receipt
    # Records isn't held up by a receipt nobody can decide on yet.
    response = await move(act, people["records_officer"], case_id, "originals_received")
    assert response.status_code == 200, response.text
    return case_id


async def test_without_a_code_the_desk_must_enter_one_before_verify(act, people):
    case_id = await _at_desk_without_code(act, people)
    response = await move(act, people["desk"], case_id, "verified")
    assert response.status_code == 409
    detail = response.json()["detail"]
    assert "HS code hasn't been confirmed" in detail
    assert "isn't known yet whether receipt (cement imports) is needed" in detail

    entered = await confirm_hs_code(act, people, case_id, "7210.49")
    assert entered.json()["hs_code"] is None  # the applicant gave none; the desk's is kept apart
    assert entered.json()["hs_code_confirmed"] == "721049"
    assert (await move(act, people["desk"], case_id, "verified")).status_code == 200


async def test_when_the_desk_enters_a_cement_code_the_receipt_is_needed(act, people, db_session):
    case_id = await _at_desk_without_code(act, people, certificate_of_origin_numbers=["CO-NO-CODE"])
    assert (await confirm_hs_code(act, people, case_id, "2523.29")).status_code == 200
    assert await _receipt_applies(act, people, case_id) is True
    response = await move(act, people["desk"], case_id, "verified")
    assert response.status_code == 409
    assert "Receipt (cement imports) is missing" in response.json()["detail"]

    assert (await upload(act, people["applicant"], case_id, "cement_receipt")).status_code == 201
    assert (await move(act, people["desk"], case_id, "verified")).status_code == 200

    [event] = await db_session.scalars(
        select(AuditEvent).where(AuditEvent.entity_id == str(case_id), AuditEvent.action == "case.hs_code_confirmed")
    )
    assert event.details["declared"] is None


# --- Confirming it -----------------------------------------------------------


async def test_the_desk_confirms_the_code_and_it_is_audited(act, people, db_session):
    case_id = await _at_desk(act, people)
    response = await confirm_hs_code(act, people, case_id, "7210.41")
    assert response.status_code == 200, response.text
    assert response.json()["hs_code"] == "721049"  # what the applicant declared stays
    assert response.json()["hs_code_confirmed"] == "721041"

    [event] = await db_session.scalars(
        select(AuditEvent).where(AuditEvent.entity_id == str(case_id), AuditEvent.action == "case.hs_code_confirmed")
    )
    assert event.actor_user_id == people["desk"].id
    assert event.details == {"declared": "721049", "confirmed": "721041", "previously_confirmed": None}


@pytest.mark.parametrize("who", ["applicant", "records_officer", "permanent_secretary"])
async def test_only_the_verifying_officer_may_confirm(act, people, who):
    case_id = await _at_desk(act, people)
    response = await act(people[who], "post", f"/etls/facility-letters/{case_id}/hs-code", json={"hs_code": "2523.29"})
    assert response.status_code == 403


async def test_it_is_confirmed_during_verification_not_before_or_after(act, people):
    case_id = (await _submit(act, people)).json()["case_id"]
    assert (await confirm_hs_code(act, people, case_id)).status_code == 403  # still with Records

    # Its own certificate number, or the duplicate check (step 6b) would hold it.
    case_id = await _at_desk(act, people, certificate_of_origin_numbers=["CO-SECOND"])
    assert (await confirm_hs_code(act, people, case_id)).status_code == 200
    assert (await move(act, people["desk"], case_id, "verified")).status_code == 200
    assert (await confirm_hs_code(act, people, case_id, "2523.29")).status_code == 403  # too late


async def test_verify_needs_a_confirmed_code(act, people):
    case_id = await _at_desk(act, people)
    response = await move(act, people["desk"], case_id, "verified")
    assert response.status_code == 409
    assert "HS code hasn't been confirmed" in response.json()["detail"]


# --- The receipt rule follows the confirmed code -----------------------------


async def test_an_officer_correcting_the_code_to_cement_makes_the_receipt_required(act, people):
    case_id = await _at_desk(act, people, hs_code="7210.49")
    assert await _receipt_applies(act, people, case_id) is False

    assert (await confirm_hs_code(act, people, case_id, "2523.29")).status_code == 200
    assert await _receipt_applies(act, people, case_id) is True
    response = await move(act, people["desk"], case_id, "verified")
    assert response.status_code == 409
    assert "Receipt (cement imports) is missing" in response.json()["detail"]

    assert (await upload(act, people["applicant"], case_id, "cement_receipt")).status_code == 201
    assert (await move(act, people["desk"], case_id, "verified")).status_code == 200


async def test_an_officer_correcting_the_code_away_from_cement_drops_the_receipt(act, people):
    case_id = (await _submit(act, people, hs_code="2523.29")).json()["case_id"]
    assert await _receipt_applies(act, people, case_id) is True
    await ready_for_records(act, people, case_id)  # uploads the receipt too, since it applies
    assert (await move(act, people["records_officer"], case_id, "originals_received")).status_code == 200

    assert (await confirm_hs_code(act, people, case_id, "6810.11")).status_code == 200  # cement blocks, not cement
    assert await _receipt_applies(act, people, case_id) is False
    assert (await move(act, people["desk"], case_id, "verified")).status_code == 200
