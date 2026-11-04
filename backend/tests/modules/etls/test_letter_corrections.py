"""Correcting a signed facility letter: cancel it with a reason, sign a corrected one.

Both files stay stored; the cancelled one is marked, never deleted.
"""

import hashlib
from datetime import timedelta

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError

from app.core.audit.models import AuditEvent
from app.core.documents import issued, storage
from app.core.workflow.delegation import today
from app.modules.etls import letter
from tests.support import facility_letter_form, move, ready_for_records, ready_to_verify, send_to_gra

pytestmark = pytest.mark.anyio

REASON = "Wrong HS code on the letter"


async def _signed_case(act, people, **form) -> int:
    case_id = (await act(people["applicant"], "post", "/etls/facility-letters", json=facility_letter_form(**form))).json()[
        "case_id"
    ]
    await ready_for_records(act, people, case_id)
    assert (await move(act, people["records_officer"], case_id, "originals_received")).status_code == 200
    await _verify_and_sign(act, people, case_id)
    return case_id


async def _verify_and_sign(act, people, case_id, hs_code="7210.49", signer="director"):
    assert (await ready_to_verify(act, people, case_id, hs_code)).status_code == 200
    assert (await move(act, people["desk"], case_id, "verified")).status_code == 200
    response = await move(act, people[signer], case_id, "signed")
    assert response.status_code == 200, response.text


async def _cancel(act, people, case_id, reason=REASON, who="director"):
    return await move(act, people[who], case_id, "originals_received", comment=reason)


async def _listing(act, people, case_id) -> list[dict]:
    response = await act(people["desk"], "get", f"/etls/facility-letters/{case_id}/letters")
    assert response.status_code == 200, response.text
    return response.json()


async def _events(db_session, case_id, action) -> list[AuditEvent]:
    return list(
        await db_session.scalars(
            select(AuditEvent)
            .where(AuditEvent.entity_id == str(case_id), AuditEvent.action == action)
            .order_by(AuditEvent.id)
        )
    )


# --- Cancelling --------------------------------------------------------------


async def test_the_ps_cancels_a_signed_letter_with_a_reason(act, people, db_session, document_storage):
    case_id = await _signed_case(act, people)
    [original] = await _listing(act, people, case_id)

    response = await _cancel(act, people, case_id)
    assert response.status_code == 200, response.text
    assert response.json()["status"]["code"] == "originals_received"  # back to the desk

    [cancelled] = await _listing(act, people, case_id)
    assert cancelled["id"] == original["id"]
    assert cancelled["status"] == "cancelled"
    assert cancelled["cancellation_reason"] == REASON
    assert cancelled["cancelled_by"] == people["director"].id
    assert cancelled["cancelled_at"] is not None

    # The file is kept, unchanged, and still downloadable, marked as cancelled.
    document = (await issued.all_issued(db_session, case_id, letter.KIND))[0]
    assert storage.path_for(document.storage_key).exists()
    old = await act(people["desk"], "get", cancelled["download_url"])
    assert old.status_code == 200
    assert old.headers["x-letter-status"] == "cancelled"
    assert hashlib.sha256(old.content).hexdigest() == original["sha256"]

    # There's no current letter until a corrected one is signed.
    default = await act(people["desk"], "get", f"/etls/facility-letters/{case_id}/letter.pdf")
    assert default.status_code == 409
    assert "cancelled" in default.json()["detail"]

    [event] = await _events(db_session, case_id, "case.document_cancelled")
    assert event.actor_user_id == people["director"].id
    assert event.details == {
        "issued_document_id": original["id"],
        "kind": letter.KIND,
        "sha256": original["sha256"],
        "reason": REASON,
    }


@pytest.mark.parametrize("reason", [None, "", "   "])
async def test_cancelling_needs_a_written_reason(act, people, reason):
    case_id = await _signed_case(act, people)
    response = await _cancel(act, people, case_id, reason=reason)
    assert response.status_code == 422
    assert "reason" in response.json()["detail"]
    assert (await _listing(act, people, case_id))[0]["status"] == "current"


async def test_the_cancel_button_says_it_needs_a_reason(act, people):
    case_id = await _signed_case(act, people)
    actions = (await act(people["director"], "get", f"/cases/{case_id}")).json()["available_actions"]
    [cancel] = [a for a in actions if a["to_status"] == "originals_received"]
    assert cancel["name"] == "Cancel the signed letter"
    assert cancel["requires_comment"] is True


@pytest.mark.parametrize("who", ["desk", "records_officer", "minister", "permanent_secretary"])
async def test_only_the_signer_may_cancel(act, people, who):
    """The Director, for anything but cement (the Minister and the PS cancel
    cement letters: test_signing_rules.py)."""
    case_id = await _signed_case(act, people)
    assert (await _cancel(act, people, case_id, who=who)).status_code == 403


async def test_someone_acting_for_the_director_may_cancel(act, people, db_session):
    case_id = await _signed_case(act, people)
    start, end = today().isoformat(), (today() + timedelta(days=3)).isoformat()
    delegated = await act(
        people["director"],
        "post",
        "/delegations",
        json={"from_position": "director_of_industry", "to_position": "dps_admin_finance", "starts_on": start, "ends_on": end},
    )
    assert delegated.status_code == 201, delegated.text

    assert (await _cancel(act, people, case_id, who="dps")).status_code == 200
    moves = await _events(db_session, case_id, "case.status_changed")
    assert moves[-1].details["on_behalf_of"] == "director_of_industry"
    assert moves[-1].details["comment"] == REASON
    assert (await _listing(act, people, case_id))[0]["cancelled_by"] == people["dps"].id


async def test_a_letter_already_sent_to_gra_can_be_cancelled(act, people):
    # "Sent to GRA" is final, but cancelling is a correction move, which may leave it.
    case_id = await _signed_case(act, people)
    assert (await send_to_gra(act, people, case_id)).status_code == 200
    assert (await _cancel(act, people, case_id)).status_code == 200


# --- The corrected letter ----------------------------------------------------


async def test_a_corrected_letter_is_issued_and_served_by_default(act, people, db_session):
    case_id = await _signed_case(act, people)
    url = f"/etls/facility-letters/{case_id}/letter.pdf"
    first = await act(people["desk"], "get", url)
    assert (await _cancel(act, people, case_id)).status_code == 200

    # The desk corrects the code and verifies again; the PS signs again.
    await _verify_and_sign(act, people, case_id, hs_code="7210.41")

    old, new = await _listing(act, people, case_id)
    assert (old["status"], new["status"]) == ("cancelled", "current")
    assert new["replaces_id"] == old["id"]
    assert new["filename"].endswith("-2.pdf")

    default = await act(people["desk"], "get", url)
    assert default.status_code == 200
    assert default.headers["x-letter-status"] == "current"
    # Different files even though nothing printed changed (the HS code isn't on
    # the letter): each issue's number is in the PDF's information block.
    assert default.headers["x-checksum-sha256"] == new["sha256"] != old["sha256"]
    assert b"(Issue 2)" in default.content and b"(Issue 1)" in first.content
    # The cancelled one still downloads, byte for byte as it was issued.
    assert (await act(people["desk"], "get", old["download_url"])).content == first.content

    issued_events = await _events(db_session, case_id, "case.document_issued")
    assert [e.details["replaces_issued_document_id"] for e in issued_events] == [None, old["id"]]


async def test_a_corrected_letter_can_be_cancelled_too(act, people):
    case_id = await _signed_case(act, people)
    for _ in range(2):
        assert (await _cancel(act, people, case_id)).status_code == 200
        await _verify_and_sign(act, people, case_id)
    statuses = [item["status"] for item in await _listing(act, people, case_id)]
    assert statuses == ["cancelled", "cancelled", "current"]


async def test_applicants_cannot_list_or_download_letters(act, people):
    case_id = await _signed_case(act, people)
    letter_id = (await _listing(act, people, case_id))[0]["id"]
    base = f"/etls/facility-letters/{case_id}"
    assert (await act(people["applicant"], "get", f"{base}/letters")).status_code == 403
    assert (await act(people["applicant"], "get", f"{base}/letters/{letter_id}/file")).status_code == 403


async def test_a_letter_from_another_case_is_not_found(act, people):
    first = await _signed_case(act, people)
    second = await _signed_case(act, people, certificate_of_origin_numbers=["CO-OTHER"])
    other_letter = (await _listing(act, people, second))[0]["id"]
    response = await act(people["desk"], "get", f"/etls/facility-letters/{first}/letters/{other_letter}/file")
    assert response.status_code == 404


# --- The database keeps the rules even against raw SQL ------------------------


async def test_a_cancellation_cannot_be_undone_or_a_letter_deleted(act, people, db_session, owner_session):
    case_id = await _signed_case(act, people)
    assert (await _cancel(act, people, case_id)).status_code == 200
    letter_id = (await _listing(act, people, case_id))[0]["id"]

    # The app (the only one who could see these uncommitted rows) can't un-cancel.
    with pytest.raises(DBAPIError, match="cancelled document can't be changed"):
        async with db_session.begin_nested():
            await db_session.execute(
                text("UPDATE core.issued_documents SET cancelled_at = NULL, cancelled_by = NULL, "
                     "cancellation_reason = NULL WHERE id = :id"),
                {"id": letter_id},
            )


async def _owner_letter(owner_session) -> int:
    """An issued document made directly as the owner (who bypasses the app's grants)."""
    return await owner_session.scalar(
        text(
            """
            WITH u AS (
                INSERT INTO core.users (email, full_name, password_hash)
                VALUES ('owner-test@test.gm', 'Owner Test', 'x') RETURNING id
            ), c AS (
                INSERT INTO core.cases (workflow_id, current_status_id, created_by)
                SELECT w.id, s.id, u.id FROM core.workflows w
                JOIN core.workflow_statuses s ON s.workflow_id = w.id AND s.code = 'signed', u
                WHERE w.code = 'etls_facility_letter' RETURNING id, created_by
            )
            INSERT INTO core.issued_documents (case_id, kind, filename, content_type, size_bytes, sha256,
                storage_key, template_version, template_sha256, issued_by)
            SELECT c.id, 'etls_facility_letter', 'f.pdf', 'application/pdf', 1, 'a', 'k', 'v', 't', c.created_by
            FROM c RETURNING id
            """
        )
    )


@pytest.mark.parametrize(
    "statement, message",
    [
        ("DELETE FROM core.issued_documents WHERE id = :id", "never deleted"),
        ("UPDATE core.issued_documents SET sha256 = 'x' WHERE id = :id", "only a cancellation"),
    ],
    ids=["delete", "edit"],
)
async def test_even_the_owner_cannot_delete_or_edit_an_issued_document(owner_session, statement, message):
    letter_id = await _owner_letter(owner_session)
    with pytest.raises(DBAPIError, match=message):
        async with owner_session.begin_nested():
            await owner_session.execute(text(statement), {"id": letter_id})


async def test_only_one_current_letter_per_case(owner_session):
    letter_id = await _owner_letter(owner_session)
    with pytest.raises(DBAPIError, match="issued_documents_one_current"):
        async with owner_session.begin_nested():
            await owner_session.execute(
                text(
                    "INSERT INTO core.issued_documents (case_id, kind, filename, content_type, size_bytes, sha256, "
                    "storage_key, template_version, template_sha256, issued_by) "
                    "SELECT case_id, kind, 'g.pdf', content_type, 1, 'b', 'k2', 'v', 't', issued_by "
                    "FROM core.issued_documents WHERE id = :id"
                ),
                {"id": letter_id},
            )
