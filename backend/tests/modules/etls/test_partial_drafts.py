"""Partial drafts (SCREENS.md global rules, A2): the applicant may save a
half-filled form and come back; Submit says what's still missing."""

import pytest

from tests.support import certificate, facility_letter_form, move, submit, submitted_case, upload_required

pytestmark = pytest.mark.anyio

URL = "/etls/facility-letters"


async def _submit_action(act, user, case_id) -> dict:
    case = (await act(user, "get", f"/cases/{case_id}")).json()
    [action] = [a for a in case["available_actions"] if a["to_status"] == "submitted"]
    return action


async def test_an_empty_draft_can_be_saved(act, people):
    response = await act(people["applicant"], "post", URL, json={})
    assert response.status_code == 201, response.text
    draft = response.json()
    assert draft["status_label"] == "Draft"
    assert (draft["importer_name"], draft["quantity"], draft["certificates_of_origin"]) == (None, None, [])

    # It's in the applicant's list, with a goods line that says so.
    [row] = [c for c in (await act(people["applicant"], "get", "/cases")).json() if c["id"] == draft["case_id"]]
    assert row["summary"] == "Not filled in yet"


async def test_blank_boxes_are_saved_as_empty(act, people):
    form = {"importer_name": "  ", "quantity": "", "product": "Cement", "certificates_of_origin": [{"number": "CO-1", "issued_on": ""}]}
    draft = (await act(people["applicant"], "post", URL, json=form)).json()
    assert draft["importer_name"] is None and draft["quantity"] is None
    assert draft["certificates_of_origin"] == [{"number": "CO-1", "issued_on": None, "expires_on": None}]


async def test_submit_lists_every_missing_field_with_the_documents(act, people):
    case_id = (await act(people["applicant"], "post", URL, json={"product": "Cement", "unit": "tonnes"})).json()["case_id"]
    blocked = (await _submit_action(act, people["applicant"], case_id))["blocked_by"]
    for gap in [
        "Importer's business name is missing",
        "Importer's address is missing",
        "Quantity is missing",
        "Exporter's name is missing",
        "Exporter's country is missing",
        "Exporter's ETLS approval number is missing",
        "Product approval number is missing",
        "Certificate of origin number is missing",
        "Invoice is missing",  # the documents check, in the same list
    ]:
        assert gap in blocked
    assert "Product is missing" not in blocked
    assert not any("HS code" in b for b in blocked)  # the applicant may leave it to the desk

    response = await submit(act, people["applicant"], case_id)
    assert response.status_code == 409
    assert "Quantity is missing" in response.json()["detail"]


async def test_a_certificate_without_its_date_blocks_submit(act, people):
    form = facility_letter_form(certificates_of_origin=[{"number": "CO-9"}])
    case_id = (await act(people["applicant"], "post", URL, json=form)).json()["case_id"]
    await upload_required(act, people["applicant"], case_id)
    blocked = (await _submit_action(act, people["applicant"], case_id))["blocked_by"]
    assert blocked == ["Issue date of certificate of origin CO-9 is missing"]


async def test_filling_it_in_later_unblocks_submit(act, people):
    case_id = (await act(people["applicant"], "post", URL, json={"importer_name": "Kombo Ltd"})).json()["case_id"]
    await upload_required(act, people["applicant"], case_id)
    saved = await act(people["applicant"], "put", f"{URL}/{case_id}", json=facility_letter_form())
    assert saved.status_code == 200, saved.text
    assert (await _submit_action(act, people["applicant"], case_id))["blocked_by"] == []
    response = await submit(act, people["applicant"], case_id)
    assert response.status_code == 200, response.text
    assert response.json()["reference"].startswith("MOTIE/ETLS/FL/")


async def test_resubmit_is_checked_too(act, people):
    case_id = await submitted_case(act, people)
    returned = await move(act, people["records_officer"], case_id, "returned", applicant_message="Fix the exporter.")
    assert returned.status_code == 200, returned.text
    # The applicant clears a field while fixing it, and saves.
    form = facility_letter_form(exporter_name="")
    assert (await act(people["applicant"], "put", f"{URL}/{case_id}", json=form)).status_code == 200
    blocked = (await _submit_action(act, people["applicant"], case_id))["blocked_by"]
    assert blocked == ["Exporter's name is missing"]


async def test_no_letter_preview_from_a_half_filled_draft(act, people):
    case_id = (await act(people["applicant"], "post", URL, json={"product": "Cement"})).json()["case_id"]
    response = await act(people["permanent_secretary"], "get", f"{URL}/{case_id}/letter-preview.pdf")
    assert response.status_code == 409
    assert "Quantity is missing" in response.json()["detail"]


async def test_records_can_save_a_partial_walk_in(act, people):
    body = {"applicant_email": "partial@example.gm", "applicant_name": "Awa Ceesay", "form": {"product": "Rice"}}
    response = await act(people["records_officer"], "post", f"{URL}/walk-in", json=body)
    assert response.status_code == 201, response.text
    assert response.json()["product"] == "Rice"


async def test_an_edited_certificate_date_is_audited(act, people):
    case_id = (await act(people["applicant"], "post", URL, json={"certificates_of_origin": [{"number": "CO-7"}]})).json()["case_id"]
    form = {"certificates_of_origin": [certificate("CO-7")]}
    assert (await act(people["applicant"], "put", f"{URL}/{case_id}", json=form)).status_code == 200
    history = (await act(people["desk"], "get", f"/cases/{case_id}/history")).json()
    [edit] = [e for e in history if e["action"] == "case.form_updated"]
    change = edit["details"]["changes"]["certificates_of_origin"]
    assert change["from"] == [{"number": "CO-7", "issued_on": None}]
    assert change["to"][0]["issued_on"] is not None
