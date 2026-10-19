"""Certificate of origin numbers are unique across all cases.

A number used before doesn't stop the submission, but holds the case and flags
it for the ETLS desk, who must resolve it before the case can move on.
"""

import asyncio
import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.identity.models import User
from app.core.identity.service import create_user
from app.core.workflow.models import CaseFlag
from app.modules.etls import service
from app.modules.etls.schemas import FacilityLetterForm
from tests.support import TEST_PASSWORD, facility_letter_form, move

pytestmark = pytest.mark.anyio


async def _submit(act, applicant, *numbers) -> int:
    response = await act(
        applicant,
        "post",
        "/etls/facility-letters",
        json=facility_letter_form(certificate_of_origin_numbers=list(numbers)),
    )
    assert response.status_code == 201, response.text
    return response.json()["case_id"]


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

    history = (await act(people["desk"], "get", f"/cases/{second}/history")).json()
    assert [e["action"] for e in history] == ["case.created", "case.flag_raised"]
    # The first case is untouched.
    assert await _flags(act, people, first) == []


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

    assert (await move(act, people["records_officer"], case_id, "originals_received")).status_code == 200
    history = (await act(people["desk"], "get", f"/cases/{case_id}/history")).json()
    assert history[2]["action"] == "case.flag_resolved"
    assert history[2]["details"]["resolution"].startswith("Same shipment")


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
    number = f"RACE-{uuid.uuid4().hex[:12]}"
    async with AsyncSession(committing_engine, expire_on_commit=False) as setup:
        ids = []
        for _ in range(2):
            user = await create_user(
                setup, email=f"race-{uuid.uuid4().hex[:8]}@test.gm", full_name="Importer",
                password=TEST_PASSWORD, role_codes=["applicant"],
            )
            ids.append(user.id)
    form = FacilityLetterForm(**facility_letter_form(certificate_of_origin_numbers=[number]))

    async def submit(user_id: int) -> int:
        async with AsyncSession(committing_engine, expire_on_commit=False) as session:
            applicant = await session.get(User, user_id)
            return (await service.submit_facility_letter(session, actor=applicant, form=form)).case_id

    case_ids = await asyncio.gather(*(submit(i) for i in ids))

    async with AsyncSession(committing_engine) as check:
        flagged = (
            await check.scalars(select(CaseFlag.case_id).where(CaseFlag.case_id.in_(case_ids)))
        ).all()
    # Whichever came second waited for the first one's lock, saw its number, and was flagged.
    assert len(flagged) == 1
