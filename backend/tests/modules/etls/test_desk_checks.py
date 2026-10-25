"""The ETLS desk's checks (SCREENS.md S2): recorded ECOWAS list ticks, other
cases that used a certificate number, and rejecting or returning while a case is held."""

from datetime import timedelta

import pytest

from app.core.workflow.delegation import today
from tests.support import confirm_hs_code, facility_letter_form, move, ready_for_records, submit, submitted_case

pytestmark = pytest.mark.anyio

ITEMS = ["ecowas_exporter_listed", "ecowas_product_covered"]


async def _at_desk(act, people, number="CO-DK-1") -> int:
    case_id = await submitted_case(act, people, certificate_of_origin_numbers=[number])
    await ready_for_records(act, people, case_id)
    assert (await move(act, people["records_officer"], case_id, "originals_received")).status_code == 200
    return case_id


async def _tick(act, user, case_id, code, ticked=True):
    return await act(user, "put", f"/cases/{case_id}/checklist/{code}", json={"ticked": ticked})


async def _verify_blocked_by(act, people, case_id) -> list[str]:
    actions = (await act(people["desk"], "get", f"/cases/{case_id}")).json()["available_actions"]
    [verify] = [a for a in actions if a["to_status"] == "verified"]
    return verify["blocked_by"]


# --- ECOWAS list ticks -------------------------------------------------------


async def test_verify_waits_for_both_ecowas_ticks(act, people):
    case_id = await _at_desk(act, people)
    assert (await confirm_hs_code(act, people, case_id)).status_code == 200

    items = (await act(people["desk"], "get", f"/cases/{case_id}/checklist")).json()
    assert [i["code"] for i in items] == ITEMS
    assert all(i["at_current_step"] and not i["ticked"] for i in items)
    blocked = await _verify_blocked_by(act, people, case_id)
    assert "'The exporter's ETLS approval number is on the ECOWAS ETLS list' isn't ticked" in blocked

    for code in ITEMS:
        response = await _tick(act, people["desk"], case_id, code)
        assert response.status_code == 200, response.text
        assert response.json()["ticked_by"] == people["desk"].id
    assert await _verify_blocked_by(act, people, case_id) == []
    assert (await move(act, people["desk"], case_id, "verified")).status_code == 200

    history = (await act(people["desk"], "get", f"/cases/{case_id}/history")).json()
    assert sorted(e["details"]["item"] for e in history if e["action"] == "case.ticked") == ITEMS


async def test_unticking_is_recorded_and_ticking_twice_changes_nothing(act, people):
    case_id = await _at_desk(act, people)
    first = (await _tick(act, people["desk"], case_id, ITEMS[0])).json()
    again = (await _tick(act, people["desk"], case_id, ITEMS[0])).json()
    assert again["ticked_at"] == first["ticked_at"]
    assert (await _tick(act, people["desk"], case_id, ITEMS[0], ticked=False)).json()["ticked"] is False

    history = (await act(people["desk"], "get", f"/cases/{case_id}/history")).json()
    assert [e["action"] for e in history if e["action"] in ("case.ticked", "case.unticked")] == [
        "case.unticked",
        "case.ticked",
    ]  # newest first; the second tick wrote nothing


async def test_only_the_desk_ticks_and_only_at_its_step(act, people):
    case_id = await submitted_case(act, people, certificate_of_origin_numbers=["CO-DK-2"])
    # At Records' step the desk's items can't be ticked by anyone.
    assert (await _tick(act, people["desk"], case_id, ITEMS[0])).status_code == 409
    await ready_for_records(act, people, case_id)
    assert (await move(act, people["records_officer"], case_id, "originals_received")).status_code == 200

    for who in ("records_officer", "permanent_secretary"):
        assert (await _tick(act, people[who], case_id, ITEMS[0])).status_code == 403, who
    assert (await act(people["applicant"], "get", f"/cases/{case_id}/checklist")).status_code == 403
    assert (await _tick(act, people["desk"], case_id, "no_such_item")).status_code == 404


async def test_someone_acting_for_the_desk_may_tick(act, people):
    case_id = await _at_desk(act, people)
    created = await act(
        people["desk"],
        "post",
        "/delegations",
        json={
            "from_position": "etls_desk_officer",
            "to_position": "records_officer",
            "starts_on": today().isoformat(),
            "ends_on": (today() + timedelta(days=1)).isoformat(),
        },
    )
    assert created.status_code == 201, created.text
    assert (await _tick(act, people["records_officer"], case_id, ITEMS[0])).status_code == 200


async def test_a_returned_case_is_checked_again_from_scratch(act, people):
    case_id = await _at_desk(act, people)
    for code in ITEMS:
        await _tick(act, people["desk"], case_id, code)
    returned = await move(act, people["desk"], case_id, "returned", applicant_message="Wrong exporter number.")
    assert returned.status_code == 200, returned.text
    assert (await submit(act, people["applicant"], case_id)).status_code == 200
    await ready_for_records(act, people, case_id)
    assert (await move(act, people["records_officer"], case_id, "originals_received")).status_code == 200

    items = (await act(people["desk"], "get", f"/cases/{case_id}/checklist")).json()
    assert not any(i["ticked"] for i in items)


# --- Only the confirmed HS code decides the receipt (C5) -----------------------


async def test_a_declared_cement_code_does_not_decide_the_receipt(act, people):
    case_id = await submitted_case(act, people, product="Portland cement", hs_code="2523.29")
    checklist = (await act(people["applicant"], "get", f"/cases/{case_id}/documents")).json()
    receipt = next(item for item in checklist if item["type"] == "cement_receipt")
    assert receipt["applies"] is None  # not known until the desk confirms


# --- Other cases that used a number ------------------------------------------


async def test_the_desk_sees_where_the_other_case_is_now(act, people, make_user):
    first = await _at_desk(act, people, "CO-DK-DUP")
    rejected = await move(act, people["desk"], first, "rejected", applicant_message="Exporter not listed.")
    assert rejected.status_code == 200, rejected.text
    second = await _at_desk(act, people, "co-dk-dup")

    response = await act(people["desk"], "get", f"/etls/facility-letters/{second}/duplicates")
    assert response.status_code == 200, response.text
    [found] = response.json()
    assert found["number"] == "co-dk-dup"
    [other] = found["other_cases"]
    assert other["case_id"] == first
    assert other["reference"].startswith("MOTIE/ETLS/FL/")
    assert (other["status_code"], other["status"]) == ("rejected", "Rejected")
    assert other["submitted_at"] is not None
    assert (await act(people["applicant"], "get", f"/etls/facility-letters/{second}/duplicates")).status_code == 403


# --- Holds and rejecting while held (C7) ---------------------------------------


async def _flagged_at_desk(act, people) -> int:
    await submitted_case(act, people, certificate_of_origin_numbers=["CO-DK-HOLD"])
    return await _at_desk(act, people, "CO-DK-HOLD")


async def test_a_duplicate_holds_the_case_at_the_desk_not_at_records(act, people):
    case_id = await _flagged_at_desk(act, people)  # Records accepted it while flagged
    assert (await confirm_hs_code(act, people, case_id)).status_code == 200
    for code in ITEMS:
        await _tick(act, people["desk"], case_id, code)
    blocked = await _verify_blocked_by(act, people, case_id)
    assert [r for r in blocked if r.startswith("On hold:")]
    assert (await move(act, people["desk"], case_id, "verified")).status_code == 409


async def test_the_desk_rejects_while_held_and_the_reason_resolves_the_flag(act, people):
    case_id = await _flagged_at_desk(act, people)
    actions = (await act(people["desk"], "get", f"/cases/{case_id}")).json()["available_actions"]
    [reject] = [a for a in actions if a["to_status"] == "rejected"]
    assert reject["blocked_by"] == []  # rejecting isn't held

    response = await move(
        act,
        people["desk"],
        case_id,
        "rejected",
        comment="Same certificate as an earlier import; exporter confirmed one shipment only.",
        applicant_message="This certificate of origin was already used.",
    )
    assert response.status_code == 200, response.text

    [flag] = (await act(people["desk"], "get", f"/cases/{case_id}/flags")).json()
    assert flag["resolved_by"] == people["desk"].id
    assert flag["resolution"] == "Reject: Same certificate as an earlier import; exporter confirmed one shipment only."
    history = (await act(people["desk"], "get", f"/cases/{case_id}/history")).json()
    [resolved] = [e for e in history if e["action"] == "case.flag_resolved"]
    assert resolved["details"]["by_move"] == "Reject"


# [CONFIRM] with the desk, like rejecting while held (migration 0037).
async def test_the_desk_returns_while_held_and_the_reason_resolves_the_flag(act, people):
    case_id = await _flagged_at_desk(act, people)
    actions = (await act(people["desk"], "get", f"/cases/{case_id}")).json()["available_actions"]
    [give_back] = [a for a in actions if a["to_status"] == "returned"]
    assert give_back["blocked_by"] == []  # returning isn't held any more

    response = await move(
        act,
        people["desk"],
        case_id,
        "returned",
        comment="Number used on an earlier case; ask for the right certificate.",
        applicant_message="This certificate of origin number was already used. Please check it.",
    )
    assert response.status_code == 200, response.text
    [flag] = (await act(people["desk"], "get", f"/cases/{case_id}/flags")).json()
    assert flag["resolution"] == "Return to applicant: Number used on an earlier case; ask for the right certificate."
    # The applicant sees the message, never the flag or the minute.
    timeline = (await act(people["applicant"], "get", f"/cases/{case_id}/timeline")).json()
    assert timeline[-1]["message"] == "This certificate of origin number was already used. Please check it."


async def test_resubmitting_the_same_number_raises_the_flag_again(act, people):
    case_id = await _flagged_at_desk(act, people)
    returned = await move(act, people["desk"], case_id, "returned", applicant_message="Please check the certificate.")
    assert returned.status_code == 200, returned.text
    assert (await submit(act, people["applicant"], case_id)).status_code == 200  # unchanged
    case_flags = (await act(people["desk"], "get", f"/cases/{case_id}/flags")).json()
    assert [f["resolved_at"] is None for f in case_flags] == [False, True]  # the old one resolved, a new one open


async def test_resubmitting_a_corrected_number_raises_no_new_flag(act, people):
    case_id = await _flagged_at_desk(act, people)
    await move(act, people["desk"], case_id, "returned", applicant_message="Please check the certificate.")
    form = facility_letter_form(certificate_of_origin_numbers=["CO-DK-FIXED"])
    assert (await act(people["applicant"], "put", f"/etls/facility-letters/{case_id}", json=form)).status_code == 200
    assert (await submit(act, people["applicant"], case_id)).status_code == 200
    case_flags = (await act(people["desk"], "get", f"/cases/{case_id}/flags")).json()
    assert all(f["resolved_at"] is not None for f in case_flags)


async def test_verify_is_still_held(act, people):
    case_id = await _flagged_at_desk(act, people)
    assert [r for r in await _verify_blocked_by(act, people, case_id) if r.startswith("On hold:")]
