"""The Records step "originals received" on a facility letter.

Records may only confirm when every required document is uploaded and the
original certificate of origin has been marked as seen in person. The
applicant can't submit without the documents, so at Records it's the
original that's usually left to do.
"""

from datetime import timedelta

import pytest
from sqlalchemy import text

from app.core.workflow import checks
from app.core.workflow.delegation import today
from tests.support import (
    FACILITY_LETTER_DOCUMENTS,
    create_draft,
    move,
    ready_for_records,
    submit,
    upload,
)

pytestmark = pytest.mark.anyio

async def _case(act, people, **form) -> int:
    return await create_draft(act, people["applicant"], **form)


async def _submitted(act, people, **form) -> tuple[int, dict[str, int]]:
    """A submitted case with every document uploaded, and the uploads' ids."""
    case_id = await _case(act, people, **form)
    ids = await _upload_all(act, people, case_id, FACILITY_LETTER_DOCUMENTS)
    assert (await submit(act, people["applicant"], case_id)).status_code == 200
    return case_id, ids


async def _upload_all(act, people, case_id, types) -> dict[str, int]:
    ids = {}
    for code in types:
        response = await upload(act, people["applicant"], case_id, code)
        assert response.status_code == 201, response.text
        ids[code] = response.json()["id"]
    return ids


async def _confirm(act, people, case_id):
    return await move(act, people["records_officer"], case_id, "originals_received")


def _seen_url(case_id, document_id):
    return f"/cases/{case_id}/documents/{document_id}/original-seen"


async def test_the_applicant_cannot_submit_with_documents_missing(act, people):
    case_id = await _case(act, people)
    await _upload_all(act, people, case_id, ["invoice"])

    response = await submit(act, people["applicant"], case_id)
    assert response.status_code == 409
    assert "Export declaration is missing" in response.json()["detail"]
    assert "Invoice is missing" not in response.json()["detail"]


async def test_records_cannot_mark_an_original_before_the_case_is_submitted(act, people):
    case_id = await _case(act, people)
    ids = await _upload_all(act, people, case_id, ["certificate_of_origin"])
    url = _seen_url(case_id, ids["certificate_of_origin"])
    assert (await act(people["records_officer"], "post", url)).status_code == 403


async def test_the_original_certificate_must_be_seen_in_person(act, people, db_session):
    case_id, ids = await _submitted(act, people)

    response = await _confirm(act, people, case_id)
    assert response.status_code == 409
    assert response.json()["detail"] == (
        "Not ready: the original certificate of origin hasn't been marked as seen"
    )

    seen = await act(people["records_officer"], "post", _seen_url(case_id, ids["certificate_of_origin"]))
    assert seen.status_code == 200, seen.text
    assert seen.json()["original_seen_by"] == people["records_officer"].id

    assert (await _confirm(act, people, case_id)).status_code == 200
    history = (await act(people["desk"], "get", f"/cases/{case_id}/history")).json()
    [event] = [e for e in history if e["action"] == "case.original_seen"]
    assert event["actor_user_id"] == people["records_officer"].id
    assert event["details"]["type"] == "certificate_of_origin"


async def test_a_new_scan_after_the_original_was_seen_must_be_seen_again(act, people):
    case_id = await _case(act, people)
    await ready_for_records(act, people, case_id)
    # The applicant uploads a different certificate scan afterwards.
    await upload(act, people["applicant"], case_id, "certificate_of_origin")

    assert (await _confirm(act, people, case_id)).status_code == 409


async def test_only_the_officer_receiving_originals_can_mark_them(act, people):
    case_id, ids = await _submitted(act, people)
    url = _seen_url(case_id, ids["certificate_of_origin"])

    for who in ("applicant", "desk", "permanent_secretary"):
        assert (await act(people[who], "post", url)).status_code == 403, who


async def test_someone_acting_for_records_can_mark_them(act, people):
    # The Records Officer delegates to the ETLS desk post for two days. Marking
    # originals follows the same rules as the Records move itself.
    case_id, ids = await _submitted(act, people)
    created = await act(
        people["records_officer"],
        "post",
        "/delegations",
        json={
            "from_position": "records_officer",
            "to_position": "etls_desk_officer",
            "starts_on": today().isoformat(),
            "ends_on": (today() + timedelta(days=2)).isoformat(),
        },
    )
    assert created.status_code == 201, created.text
    url = _seen_url(case_id, ids["certificate_of_origin"])
    assert (await act(people["desk"], "post", url)).status_code == 200


async def test_only_documents_whose_original_is_required(act, people):
    case_id, ids = await _submitted(act, people)
    assert (await act(people["records_officer"], "post", _seen_url(case_id, ids["invoice"]))).status_code == 422


async def test_marking_twice_changes_nothing(act, people):
    case_id, ids = await _submitted(act, people)
    url = _seen_url(case_id, ids["certificate_of_origin"])
    first = (await act(people["records_officer"], "post", url)).json()
    again = (await act(people["records_officer"], "post", url)).json()
    assert again["original_seen_at"] == first["original_seen_at"]


async def test_a_declared_cement_import_passes_records_without_the_receipt(act, people):
    # Only the desk's confirmed code decides the receipt (SCREENS.md A2), and the
    # desk comes after Records: neither Submit nor Records waits for it.
    case_id, _ = await _submitted(act, people, product="Portland cement", hs_code="2523.29")
    await ready_for_records(act, people, case_id)
    assert (await _confirm(act, people, case_id)).status_code == 200


async def test_the_same_documents_are_enough_for_a_non_cement_import(act, people):
    case_id = await _case(act, people, product="Roofing sheets", hs_code="7210.49")
    await ready_for_records(act, people, case_id)
    assert (await _confirm(act, people, case_id)).status_code == 200


async def test_every_check_named_in_the_database_has_code_behind_it(db_session):
    codes = set((await db_session.scalars(text("SELECT DISTINCT check_code FROM core.transition_checks"))).all())
    assert codes and codes <= checks.registered()


async def test_a_check_with_no_code_behind_it_blocks_the_move(act, people, monkeypatch):
    case_id = await _case(act, people)
    await ready_for_records(act, people, case_id)
    monkeypatch.delitem(checks._checks, "originals_seen")

    response = await _confirm(act, people, case_id)
    assert response.status_code == 409
    assert "isn't available" in response.json()["detail"]
