"""Certificate of origin numbers are unique across all submitted cases.

A number used before doesn't stop the submission, but holds the case and flags
it for the ETLS desk, who must resolve it before the case can move on. The
check runs when the applicant submits; a draft's numbers don't count.
"""

import asyncio
import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.documents import service as documents
from app.core.identity.models import User
from app.core.identity.service import create_user
from app.core.workflow import service as workflow
from app.core.workflow.models import CaseFlag
from app.modules.etls import service
from app.modules.etls.schemas import FacilityLetterForm
from tests.support import (
    FACILITY_LETTER_DOCUMENTS,
    PDF,
    TEST_PASSWORD,
    create_draft,
    facility_letter_form,
    move,
    ready_for_records,
    submit,
    upload_required,
)

pytestmark = pytest.mark.anyio


async def _submit(act, applicant, *numbers) -> int:
    case_id = await create_draft(act, applicant, certificate_of_origin_numbers=list(numbers))
    await upload_required(act, applicant, case_id)
    response = await submit(act, applicant, case_id)
    assert response.status_code == 200, response.text
    return case_id


async def _flags(act, people, case_id) -> list[dict]:
    response = await act(people["desk"], "get", f"/cases/{case_id}/flags")
    assert response.status_code == 200, response.text
    return response.json()


async def test_a_new_number_raises_no_flag(act, people):
    case_id = await _submit(act, people["applicant"], "GM-CO-1")
    assert await _flags(act, people, case_id) == []
    assert (await act(people["records_officer"], "get", f"/cases/{case_id}")).json()["on_hold"] is False


async def test_a_reused_number_holds_the_case_for_the_desk(act, people, make_user):
    first = await _submit(act, people["applicant"], "SN-CO-2026-0042")
    # Another importer, the same certificate written differently.
    second = await _submit(act, await make_user("applicant"), "sn-co-2026-0042 ")

    [flag] = await _flags(act, people, second)
    assert flag["code"] == "etls.duplicate_certificate_of_origin"
    assert flag["for_position"] == "etls_desk_officer"
    assert flag["details"]["numbers"] == ["SN-CO-2026-0042"]
    assert flag["details"]["earlier_case_ids"] == {"SN-CO-2026-0042": [first]}
    assert flag["resolved_at"] is None

    case = (await act(people["records_officer"], "get", f"/cases/{second}")).json()
    assert case["on_hold"] is True
    # Records can't confirm the originals while the case is held.
    response = await move(act, people["records_officer"], second, "originals_received")
    assert response.status_code == 409
    assert "SN-CO-2026-0042" in response.json()["detail"]

    history = (await act(people["desk"], "get", f"/cases/{second}/history")).json()[::-1]  # oldest first
    # Raised by submitting, together with the move.
    assert [e["action"] for e in history][-3:] == ["case.status_changed", "case.reference_assigned", "case.flag_raised"]
    # The first case is untouched.
    assert await _flags(act, people, first) == []


async def test_a_drafts_numbers_are_not_used_yet(act, people, make_user):
    # Someone else's unsubmitted draft holds nobody up.
    await create_draft(act, await make_user("applicant"), certificate_of_origin_numbers=["CO-DRAFT-1"])
    case_id = await _submit(act, people["applicant"], "CO-DRAFT-1")
    assert await _flags(act, people, case_id) == []


async def test_editing_a_draft_does_not_raise_a_flag_until_it_is_submitted(act, people):
    await _submit(act, people["applicant"], "CO-EDIT-1")
    case_id = await create_draft(act, people["applicant"], certificate_of_origin_numbers=["CO-EDIT-2"])
    response = await act(
        people["applicant"], "put", f"/etls/facility-letters/{case_id}",
        json=facility_letter_form(certificate_of_origin_numbers=["CO-EDIT-1"]),
    )
    assert response.status_code == 200, response.text
    assert await _flags(act, people, case_id) == []
    await upload_required(act, people["applicant"], case_id)
    assert (await submit(act, people["applicant"], case_id)).status_code == 200
    [flag] = await _flags(act, people, case_id)
    assert flag["details"]["numbers"] == ["CO-EDIT-1"]


async def test_the_desk_resolves_the_flag_and_the_case_moves_on(act, people):
    await _submit(act, people["applicant"], "CO-7")
    case_id = await _submit(act, people["applicant"], "CO-7")
    [flag] = await _flags(act, people, case_id)
    resolve = f"/cases/{case_id}/flags/{flag['id']}/resolve"

    assert (await act(people["records_officer"], "post", resolve, json={"resolution": "fine"})).status_code == 403
    assert (await act(people["desk"], "post", resolve, json={"resolution": ""})).status_code == 422
    response = await act(
        people["desk"], "post", resolve, json={"resolution": "Same shipment, split in two; checked with exporter"}
    )
    assert response.status_code == 200, response.text
    assert response.json()["resolved_by"] == people["desk"].id
    assert (await act(people["desk"], "post", resolve, json={"resolution": "again"})).status_code == 409

    await ready_for_records(act, people, case_id)
    assert (await move(act, people["records_officer"], case_id, "originals_received")).status_code == 200
    history = (await act(people["desk"], "get", f"/cases/{case_id}/history")).json()
    [resolved] = [e for e in history if e["action"] == "case.flag_resolved"]
    assert resolved["details"]["resolution"].startswith("Same shipment")


async def test_only_the_repeated_numbers_are_listed(act, people):
    await _submit(act, people["applicant"], "CO-A", "CO-B")
    case_id = await _submit(act, people["applicant"], "CO-B", "CO-C")
    [flag] = await _flags(act, people, case_id)
    assert flag["details"]["numbers"] == ["CO-B"]


async def test_applicants_cannot_see_flags(act, people):
    await _submit(act, people["applicant"], "CO-9")
    case_id = await _submit(act, people["applicant"], "CO-9")
    assert (await act(people["applicant"], "get", f"/cases/{case_id}")).json()["on_hold"] is None
    assert (await act(people["applicant"], "get", f"/cases/{case_id}/flags")).status_code == 403


async def test_two_submissions_at_the_same_moment_cannot_both_slip_through(committing_engine, monkeypatch):
    # Real commits on two connections, like two importers clicking at once.
    # Unique number and emails, because these rows stay until the next run.

    # Widen the window: each submission waits half a second after its check,
    # before committing. Without the advisory lock, the second one checks
    # during that wait, can't see the first one's uncommitted rows, and both
    # go through unflagged. With the lock, the second waits for the first commit.
    check = service._earlier_uses

    async def slow_check(*args):
        result = await check(*args)
        await asyncio.sleep(0.5)
        return result

    monkeypatch.setattr(service, "_earlier_uses", slow_check)
    # Submitting also takes the next case reference, whose counter row lock
    # would make the two wait for each other anyway. Hand out references
    # without a lock, so only the advisory lock is being tested.
    monkeypatch.setattr(workflow, "next_reference", lambda session, wf: _unlocked_reference())

    number = f"RACE-{uuid.uuid4().hex[:12]}"
    form = FacilityLetterForm(**facility_letter_form(certificate_of_origin_numbers=[number]))
    drafts = []  # (user id, case id)
    async with AsyncSession(committing_engine, expire_on_commit=False) as setup:
        for _ in range(2):
            user = await create_user(
                setup, email=f"race-{uuid.uuid4().hex[:8]}@test.gm", full_name="Importer",
                password=TEST_PASSWORD, role_codes=["applicant"],
            )
            case_id = (await service.create_draft(setup, actor=user, form=form)).case_id
            for type_code in FACILITY_LETTER_DOCUMENTS:
                await documents.upload(
                    setup, case_id=case_id, type_code=type_code, filename="scan.pdf", chunks=_chunks(PDF), actor=user
                )
            drafts.append((user.id, case_id))

    async def submit_draft(user_id: int, case_id: int) -> int:
        async with AsyncSession(committing_engine, expire_on_commit=False) as session:
            applicant = await session.get(User, user_id)
            await workflow.change_status(session, case_id=case_id, to_status_code="submitted", actor=applicant)
            return case_id

    case_ids = await asyncio.gather(*(submit_draft(*d) for d in drafts))

    async with AsyncSession(committing_engine) as check:
        flagged = (
            await check.scalars(select(CaseFlag.case_id).where(CaseFlag.case_id.in_(case_ids)))
        ).all()
    # Whichever came second waited for the first one's lock, saw its number, and was flagged.
    assert len(flagged) == 1


async def _unlocked_reference() -> str:
    return f"RACE/{uuid.uuid4().hex}"


async def _chunks(data: bytes):
    yield data
