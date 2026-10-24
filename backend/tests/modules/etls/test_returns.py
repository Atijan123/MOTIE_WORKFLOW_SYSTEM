"""Returning an application: a message to the applicant plus an internal minute; then resubmitting.

SCREENS.md global rules: a return has two texts, a message the applicant sees
and an optional minute only staff see. The case becomes editable again and
is resubmitted with the same reference and history.
"""

import pytest

from tests.support import (
    confirm_hs_code,
    facility_letter_form,
    move,
    ready_for_records,
    submit,
    submitted_case,
)

pytestmark = pytest.mark.anyio

MESSAGE = "The invoice is unreadable. Please upload a clearer scan."
MINUTE = "Third unreadable scan from this importer."


async def _return(act, user, case_id, message=MESSAGE, minute=MINUTE):
    return await act(
        user,
        "post",
        f"/cases/{case_id}/status",
        json={"to_status": "returned", "applicant_message": message, "comment": minute},
    )


async def _at_desk(act, people, **form) -> int:
    case_id = await submitted_case(act, people, **form)
    await ready_for_records(act, people, case_id)
    assert (await move(act, people["records_officer"], case_id, "originals_received")).status_code == 200
    return case_id


async def test_records_returns_with_a_message_and_a_minute(act, people):
    case_id = await submitted_case(act, people)
    actions = (await act(people["records_officer"], "get", f"/cases/{case_id}")).json()["available_actions"]
    [action] = [a for a in actions if a["to_status"] == "returned"]
    assert action["name"] == "Return to applicant"
    assert action["requires_applicant_message"] is True
    assert action["requires_comment"] is False  # the minute is optional

    response = await _return(act, people["records_officer"], case_id)
    assert response.status_code == 200, response.text

    # The applicant: the label, the message, and an editable form. Never the minute.
    case = (await act(people["applicant"], "get", f"/cases/{case_id}")).json()
    assert case["status"]["label"] == "Returned: action needed"
    assert case["status"]["editable"] is True
    assert case["applicant_message"] == MESSAGE
    [row] = [c for c in (await act(people["applicant"], "get", "/cases")).json() if c["id"] == case_id]
    assert row["applicant_message"] == MESSAGE  # the notice on "my applications"
    timeline = (await act(people["applicant"], "get", f"/cases/{case_id}/timeline")).json()
    assert timeline[-1]["label"] == "Returned: action needed"
    assert timeline[-1]["message"] == MESSAGE
    assert MINUTE not in str(case) + str(row) + str(timeline)

    # Staff see both texts in the history.
    history = (await act(people["desk"], "get", f"/cases/{case_id}/history")).json()
    [returned] = [e for e in history if e["details"].get("to") == "returned"]
    assert returned["details"]["applicant_message"] == MESSAGE
    assert returned["details"]["comment"] == MINUTE


@pytest.mark.parametrize("message", [None, "", "   "])
async def test_a_return_needs_a_message_to_the_applicant(act, people, message):
    case_id = await submitted_case(act, people)
    response = await _return(act, people["records_officer"], case_id, message=message)
    assert response.status_code == 422
    assert "message to the applicant" in response.json()["detail"]


async def test_a_message_on_a_move_that_sends_none_is_refused(act, people):
    case_id = await submitted_case(act, people)
    await ready_for_records(act, people, case_id)
    response = await act(
        people["records_officer"],
        "post",
        f"/cases/{case_id}/status",
        json={"to_status": "originals_received", "applicant_message": "Welcome!"},
    )
    assert response.status_code == 422
    assert "doesn't send the applicant a message" in response.json()["detail"]


async def test_the_applicant_fixes_it_and_resubmits_with_the_same_reference(act, people):
    case_id = await submitted_case(act, people)
    reference = (await act(people["applicant"], "get", f"/cases/{case_id}")).json()["reference"]
    assert (await _return(act, people["records_officer"], case_id)).status_code == 200

    fixed = await act(
        people["applicant"], "put", f"/etls/facility-letters/{case_id}", json=facility_letter_form(quantity="1100")
    )
    assert fixed.status_code == 200, fixed.text
    for who in ("records_officer", "desk"):
        assert (await submit(act, people[who], case_id)).status_code == 403, who
    response = await submit(act, people["applicant"], case_id)
    assert response.status_code == 200, response.text

    case = response.json()
    assert case["reference"] == reference
    assert case["status"]["label"] == "Submitted"
    assert case["applicant_message"] is None  # the notice goes once it's resubmitted
    timeline = [e["label"] for e in (await act(people["applicant"], "get", f"/cases/{case_id}/timeline")).json()]
    assert timeline == ["Draft", "Submitted", "Returned: action needed", "Resubmitted"]
    # Back with Records, who sees it first, as with every application.
    queue = (await act(people["records_officer"], "get", "/cases/queue")).json()
    assert case_id in [row["id"] for row in queue]


async def test_the_desk_returns_too_and_the_case_goes_back_through_records(act, people):
    case_id = await _at_desk(act, people)
    assert (await _return(act, people["desk"], case_id, minute=None)).status_code == 200
    assert (await submit(act, people["applicant"], case_id)).status_code == 200
    case = (await act(people["records_officer"], "get", f"/cases/{case_id}")).json()
    assert case["status"]["code"] == "submitted"


async def test_only_records_and_the_desk_return_at_their_own_steps(act, people):
    case_id = await submitted_case(act, people)
    for who in ("desk", "permanent_secretary", "applicant"):
        assert (await _return(act, people[who], case_id)).status_code == 403, who


async def test_changing_the_goods_after_a_return_clears_the_confirmed_hs_code(act, people):
    case_id = await _at_desk(act, people)
    assert (await confirm_hs_code(act, people, case_id)).status_code == 200
    assert (await _return(act, people["desk"], case_id)).status_code == 200

    form = facility_letter_form(product="Galvanised roofing sheets")
    letter = (await act(people["applicant"], "put", f"/etls/facility-letters/{case_id}", json=form)).json()
    assert letter["hs_code_confirmed"] is None
    history = (await act(people["desk"], "get", f"/cases/{case_id}/history")).json()
    [edit] = [e for e in history if e["action"] == "case.form_updated"]
    assert edit["details"]["hs_code_confirmation_cleared"] == "721049"


async def test_a_rejection_tells_the_applicant_why(act, people):
    case_id = await _at_desk(act, people)
    assert (await move(act, people["desk"], case_id, "rejected")).status_code == 422  # no reason

    response = await act(
        people["desk"],
        "post",
        f"/cases/{case_id}/status",
        json={"to_status": "rejected", "applicant_message": "The exporter is not on the ETLS list."},
    )
    assert response.status_code == 200, response.text
    case = (await act(people["applicant"], "get", f"/cases/{case_id}")).json()
    assert case["status"]["label"] == "Rejected"
    assert case["applicant_message"] == "The exporter is not on the ETLS list."
    assert case["status"]["editable"] is False
