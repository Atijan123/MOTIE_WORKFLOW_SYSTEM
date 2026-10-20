"""Case reference numbers: a sequence per service per year, assigned at submission."""

import asyncio
import re
from datetime import date

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.workflow import service
from app.core.workflow.models import Workflow
from tests.support import facility_letter_form, move, open_case, ready_for_records

pytestmark = pytest.mark.anyio

FL = re.compile(r"MOTIE/ETLS/FL/(\d{4})/(\d{4,})")


async def _submit(act, people, **form) -> dict:
    response = await act(people["applicant"], "post", "/etls/facility-letters", json=facility_letter_form(**form))
    assert response.status_code == 201, response.text
    return response.json()


def _number(reference: str) -> int:
    return int(reference.rsplit("/", 1)[1])


async def test_facility_letters_are_numbered_in_sequence(act, people):
    first = await _submit(act, people, certificate_of_origin_numbers=["CO-REF-1"])
    second = await _submit(act, people, certificate_of_origin_numbers=["CO-REF-2"])

    match = FL.fullmatch(first["reference"])
    assert match, first["reference"]
    assert int(match.group(1)) == service.today().year
    # Other tests may have committed cases this year, so check the step, not the value.
    assert _number(second["reference"]) == _number(first["reference"]) + 1


async def test_each_service_has_its_own_sequence(act, people):
    letter = await _submit(act, people)
    approval = await open_case(act, people["applicant"])
    assert approval["reference"].startswith(f"MOTIE/ETLS/AP/{service.today().year}/")
    assert letter["reference"].startswith("MOTIE/ETLS/FL/")


async def test_the_numbers_restart_each_year(act, people, monkeypatch):
    real_today = service.today()
    monkeypatch.setattr(service, "today", lambda: real_today.replace(year=2099))
    assert (await _submit(act, people))["reference"] == "MOTIE/ETLS/FL/2099/0001"
    second = await _submit(act, people, certificate_of_origin_numbers=["CO-2099-2"])
    assert second["reference"] == "MOTIE/ETLS/FL/2099/0002"


async def test_a_submission_that_fails_gives_its_number_back(db_session, people, monkeypatch):
    monkeypatch.setattr(service, "today", lambda: date(2098, 1, 1))
    with pytest.raises(RuntimeError):
        async with db_session.begin_nested():
            await service.open_case(
                db_session, workflow_code="etls_application", actor=people["applicant"], module=None
            )
            raise RuntimeError("the form failed to save")
    case = await service.open_case(db_session, workflow_code="etls_application", actor=people["applicant"], module=None)
    assert case.reference == "MOTIE/ETLS/AP/2098/0001"  # not 0002: no gap


async def test_everyone_sees_the_reference_and_it_never_changes(act, people):
    letter = await _submit(act, people)
    case_id, reference = letter["case_id"], letter["reference"]
    await ready_for_records(act, people, case_id)
    assert (await move(act, people["records_officer"], case_id, "originals_received")).status_code == 200

    for who in ("applicant", "desk"):
        case = (await act(people[who], "get", f"/cases/{case_id}")).json()
        assert case["reference"] == reference
        assert case["submitted_at"] is not None
    history = (await act(people["desk"], "get", f"/cases/{case_id}/history")).json()
    assert any(e["details"].get("reference") == reference for e in history)


async def test_two_submissions_at_the_same_moment_get_different_numbers(committing_engine, monkeypatch):
    # A year of its own, so the counter row it commits doesn't affect other
    # tests. (It stays until the next run rebuilds the test database.)
    monkeypatch.setattr(service, "today", lambda: date(2097, 6, 1))

    async def workflow(session):
        return await session.scalar(select(Workflow).where(Workflow.code == "etls_application"))

    async with AsyncSession(committing_engine) as first, AsyncSession(committing_engine) as second:
        taken_first = await service.next_reference(first, await workflow(first))
        # The second asks while the first transaction is still open: it must wait.
        waiting = asyncio.create_task(service.next_reference(second, await workflow(second)))
        await asyncio.sleep(0.5)
        assert not waiting.done()
        await first.commit()
        taken_second = await waiting
        await second.commit()

    assert _number(taken_second) == _number(taken_first) + 1
