"""Documents on facility letter cases: requirements (with the HS code rule), uploads, downloads."""

import hashlib

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.core.config import settings
from app.core.documents.conditions import holds
from tests.support import (
    FACILITY_LETTER_DOCUMENTS,
    JPEG,
    PDF,
    PNG,
    facility_letter_form,
    move,
    ready_for_records,
    upload,
)

pytestmark = pytest.mark.anyio

async def _case(act, people, **form) -> int:
    response = await act(people["applicant"], "post", "/etls/facility-letters", json=facility_letter_form(**form))
    assert response.status_code == 201, response.text
    return response.json()["case_id"]


async def _checklist(act, user, case_id) -> dict[str, dict]:
    response = await act(user, "get", f"/cases/{case_id}/documents")
    assert response.status_code == 200, response.text
    return {item["type"]: item for item in response.json()}


async def test_five_documents_are_always_required(act, people):
    checklist = await _checklist(act, people["applicant"], await _case(act, people))
    for code in FACILITY_LETTER_DOCUMENTS:
        assert checklist[code]["applies"] and checklist[code]["missing"], code
    # Not cement: the receipt doesn't apply.
    assert checklist["cement_receipt"]["applies"] is False
    assert checklist["cement_receipt"]["missing"] is False


@pytest.mark.parametrize("hs_code", ["2523.29", "252321", "2523 90 00 00"])
async def test_hs_heading_2523_also_needs_the_receipt(act, people, hs_code):
    checklist = await _checklist(act, people["applicant"], await _case(act, people, hs_code=hs_code))
    assert checklist["cement_receipt"]["applies"] is True
    assert checklist["cement_receipt"]["missing"] is True


async def test_the_product_wording_no_longer_decides(act, people):
    # The old rule matched "cement" in the text, so a cement mixer needed a receipt.
    mixer = await _case(act, people, product="Cement mixer", hs_code="8474.31")
    assert (await _checklist(act, people["applicant"], mixer))["cement_receipt"]["applies"] is False
    # ...and cement described without the word "cement" was missed.
    clinker = await _case(act, people, product="Grey clinker", hs_code="2523.10")
    assert (await _checklist(act, people["applicant"], clinker))["cement_receipt"]["applies"] is True


async def test_the_receipt_rule_is_a_row_testing_the_hs_heading(db_session):
    condition = await db_session.scalar(
        text(
            "SELECT r.condition FROM core.document_requirements r "
            "JOIN core.document_types t ON t.id = r.document_type_id "
            "JOIN core.workflows w ON w.id = r.workflow_id "
            "WHERE w.code = 'etls_facility_letter' AND t.code = 'cement_receipt'"
        )
    )
    assert condition == {"field": "hs_heading", "op": "equals", "value": "2523"}


async def test_uploading_fills_the_checklist_and_is_audited(act, people):
    case_id = await _case(act, people)
    response = await upload(act, people["applicant"], case_id, "invoice", filename="Invoice 0042.pdf")
    assert response.status_code == 201, response.text
    document = response.json()
    assert document["content_type"] == "application/pdf"
    assert document["filename"] == "Invoice 0042.pdf"
    assert document["sha256"] == hashlib.sha256(PDF).hexdigest()

    checklist = await _checklist(act, people["applicant"], case_id)
    assert checklist["invoice"]["missing"] is False
    assert [d["id"] for d in checklist["invoice"]["documents"]] == [document["id"]]

    history = (await act(people["desk"], "get", f"/cases/{case_id}/history")).json()
    assert history[-1]["action"] == "case.document_uploaded"
    assert history[-1]["details"]["sha256"] == document["sha256"]


async def test_staff_download_exactly_what_was_uploaded(act, people):
    case_id = await _case(act, people)
    document = (await upload(act, people["applicant"], case_id, "invoice")).json()

    response = await act(people["desk"], "get", f"/cases/{case_id}/documents/{document['id']}/file")
    assert response.status_code == 200
    assert response.content == PDF
    assert response.headers["content-type"] == "application/pdf"
    assert response.headers["content-disposition"].startswith("attachment")
    assert response.headers["x-content-type-options"] == "nosniff"


@pytest.mark.parametrize(
    "content, expected_type", [(PNG, "image/png"), (JPEG, "image/jpeg")], ids=["png", "jpeg"]
)
async def test_images_are_accepted(act, people, content, expected_type):
    response = await upload(act, people["applicant"], await _case(act, people), "invoice", content=content)
    assert response.status_code == 201, response.text
    assert response.json()["content_type"] == expected_type


async def test_the_file_type_comes_from_the_file_not_the_name(act, people, document_storage):
    case_id = await _case(act, people)
    # A script renamed to .pdf is still refused, and nothing is left on disk.
    script = b"#!/bin/sh\nrm -rf /"
    response = await upload(act, people["applicant"], case_id, "invoice", content=script, filename="x.pdf")
    assert response.status_code == 415
    assert list(document_storage.iterdir()) == []


async def test_empty_and_too_large_files_are_refused(act, people, monkeypatch, document_storage):
    case_id = await _case(act, people)
    assert (await upload(act, people["applicant"], case_id, "invoice", content=b"")).status_code == 422

    monkeypatch.setattr(settings, "max_upload_bytes", 1024)
    big = PDF + b"x" * 2048
    assert (await upload(act, people["applicant"], case_id, "invoice", content=big)).status_code == 413
    assert list(document_storage.iterdir()) == []


async def test_the_filename_cannot_point_anywhere(act, people, document_storage):
    case_id = await _case(act, people)
    response = await upload(act, people["applicant"], case_id, "invoice", filename="../../etc/passwd")
    assert response.json()["filename"] == "passwd"
    # On disk the file has a random name; the user's name is only for display.
    [stored] = document_storage.iterdir()
    assert stored.name != "passwd" and len(stored.name) == 32


async def test_only_document_types_the_workflow_takes(act, people):
    case_id = await _case(act, people)
    assert (await upload(act, people["applicant"], case_id, "passport")).status_code == 422


async def test_others_can_neither_upload_nor_download(act, people, make_user):
    case_id = await _case(act, people)
    document = (await upload(act, people["applicant"], case_id, "invoice")).json()
    stranger = await make_user("applicant")

    assert (await upload(act, stranger, case_id, "invoice")).status_code == 404
    url = f"/cases/{case_id}/documents/{document['id']}/file"
    assert (await act(stranger, "get", url)).status_code == 404


async def test_no_uploads_to_a_closed_case(act, people):
    case_id = await _case(act, people)
    await ready_for_records(act, people, case_id)
    for who, to_status in [("records_officer", "originals_received"), ("desk", "rejected")]:
        await move(act, people[who], case_id, to_status)
    assert (await act(people["applicant"], "get", f"/cases/{case_id}")).json()["status"]["label"] == "Rejected"

    assert (await upload(act, people["applicant"], case_id, "invoice")).status_code == 422


def test_conditions():
    cement = {"field": "product", "op": "contains", "value": "cement"}
    assert holds(None, {})
    assert holds(cement, {"product": "Grey CEMENT"})
    assert not holds(cement, {"product": "Rice"})
    assert holds({"field": "unit", "op": "equals", "value": "tonnes"}, {"unit": " Tonnes "})
    # A rule about a fact the module doesn't supply fails closed: document required.
    assert holds(cement, {}) is True
    # A fact the module supplies but that has no value yet: not known yet.
    assert holds({"field": "hs_heading", "op": "equals", "value": "2523"}, {"hs_heading": None}) is None


async def test_database_refuses_conditions_it_cannot_evaluate(owner_session):
    with pytest.raises(IntegrityError):
        await owner_session.execute(
            text(
                "INSERT INTO core.document_requirements (workflow_id, document_type_id, condition) "
                "SELECT w.id, t.id, '{\"field\": \"product\", \"op\": \"eval\", \"value\": \"x\"}'::jsonb "
                "FROM core.workflows w, core.document_types t "
                "WHERE w.code = 'etls_application' AND t.code = 'invoice'"
            )
        )
