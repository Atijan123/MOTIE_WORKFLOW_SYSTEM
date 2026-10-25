"""What the PS needs before signing (SCREENS.md S3): a summary of the checks,
a preview of the letter that is never stored, and returning the file to the desk."""

import pytest
from sqlalchemy import func, select

from app.core.documents.models import IssuedDocument
from app.core.workflow.models import Case
from app.modules.etls import letter
from tests.support import create_draft, move, ready_for_records, ready_to_verify

pytestmark = pytest.mark.anyio


async def _verified(act, people, number="CO-PS-1") -> int:
    case_id = await create_draft(act, people["applicant"], certificate_of_origin_numbers=[number])
    await ready_for_records(act, people, case_id)
    assert (await move(act, people["records_officer"], case_id, "originals_received")).status_code == 200
    assert (await ready_to_verify(act, people, case_id)).status_code == 200
    assert (await move(act, people["desk"], case_id, "verified")).status_code == 200
    return case_id


async def test_the_ps_sees_every_check_made(act, people):
    case_id = await _verified(act, people)
    response = await act(people["permanent_secretary"], "get", f"/etls/facility-letters/{case_id}/checks")
    assert response.status_code == 200, response.text
    checks = response.json()

    [original] = checks["originals"]
    assert (original["document"], original["seen"]) == ("Certificate of origin", True)
    assert original["seen_by"] == people["records_officer"].full_name
    assert [t["ticked"] for t in checks["checklist"]] == [True, True]
    assert {t["ticked_by"] for t in checks["checklist"]} == {people["desk"].full_name}
    assert checks["duplicate_flags"] == []  # no certificate number used before
    assert (checks["hs_code_confirmed"], checks["hs_code_confirmed_by"]) == ("721049", people["desk"].full_name)
    [certificate] = checks["certificates"]
    assert certificate["valid_today"] is True
    assert checks["documents_missing"] == []


async def test_applicants_cannot_see_the_checks(act, people):
    case_id = await _verified(act, people)
    response = await act(people["applicant"], "get", f"/etls/facility-letters/{case_id}/checks")
    assert response.status_code == 403


async def test_the_preview_is_marked_and_never_stored(act, people, db_session):
    case_id = await _verified(act, people)
    response = await act(people["permanent_secretary"], "get", f"/etls/facility-letters/{case_id}/letter-preview.pdf")
    assert response.status_code == 200, response.text
    assert response.headers["content-type"] == "application/pdf"
    assert response.headers["x-letter-status"] == "preview"
    assert response.headers["cache-control"] == "no-store"
    assert response.content.startswith(b"%PDF-")

    # Nothing was issued: the case still has no letter.
    count = await db_session.scalar(
        select(func.count()).select_from(IssuedDocument).where(IssuedDocument.case_id == case_id)
    )
    assert count == 0
    assert (await act(people["desk"], "get", f"/etls/facility-letters/{case_id}/letter.pdf")).status_code == 409


async def test_the_preview_says_it_is_a_draft_with_the_ministrys_wording(act, people, db_session):
    case_id = await _verified(act, people)
    fields = await letter.preview_fields(db_session, await db_session.get(Case, case_id))
    assert fields.signature_title == "Permanent Secretary"
    assert fields.signer_name == ""  # nobody has signed
    raw = letter.render_pdf(fields, preview=True, compress=False)
    assert letter.PREVIEW_MARK.encode() in raw
    assert b"REQUEST FOR ETLS FACILITY" in raw
    assert letter.PREVIEW_MARK.encode() not in letter.render_pdf(fields, compress=False)


async def test_no_preview_once_the_letter_is_signed(act, people):
    case_id = await _verified(act, people)
    assert (await move(act, people["permanent_secretary"], case_id, "signed")).status_code == 200
    response = await act(people["permanent_secretary"], "get", f"/etls/facility-letters/{case_id}/letter-preview.pdf")
    assert response.status_code == 409
    assert "letter.pdf" in response.json()["detail"]


async def test_the_ps_returns_the_file_to_the_desk_with_a_reason(act, people):
    case_id = await _verified(act, people)
    actions = (await act(people["permanent_secretary"], "get", f"/cases/{case_id}")).json()["available_actions"]
    [back] = [a for a in actions if a["to_status"] == "originals_received"]
    assert back["name"] == "Return to the desk"
    assert back["requires_comment"] is True

    assert (await move(act, people["permanent_secretary"], case_id, "originals_received")).status_code == 422
    response = await move(
        act, people["permanent_secretary"], case_id, "originals_received", comment="Check the quantity with Records"
    )
    assert response.status_code == 200, response.text
    queue = (await act(people["desk"], "get", "/cases/queue")).json()
    assert case_id in [row["id"] for row in queue]
    # The desk's earlier ticks still stand: nothing in the application changed.
    actions = (await act(people["desk"], "get", f"/cases/{case_id}")).json()["available_actions"]
    [verify] = [a for a in actions if a["to_status"] == "verified"]
    assert verify["blocked_by"] == []


async def test_only_the_ps_returns_a_verified_file(act, people):
    case_id = await _verified(act, people)
    for who in ("desk", "records_officer"):
        response = await move(act, people[who], case_id, "originals_received", comment="Please look again")
        assert response.status_code == 403, who
