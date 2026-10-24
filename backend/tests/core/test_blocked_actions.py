"""Disabled actions explain why (SCREENS.md global rules): a dry run of the move's
on-hold flags and checks, shown on the case page."""

import pytest
from sqlalchemy import func, select

from app.core.audit.models import AuditEvent
from tests.support import (
    confirm_hs_code,
    create_draft,
    move,
    ready_for_records,
    submit,
    submitted_case,
    upload_required,
)

pytestmark = pytest.mark.anyio


async def _submit(act, people, number="CO-B-1") -> int:
    return await submitted_case(act, people, certificate_of_origin_numbers=[number])


async def _action(act, user, case_id, to_status) -> dict:
    case = (await act(user, "get", f"/cases/{case_id}")).json()
    [action] = [a for a in case["available_actions"] if a["to_status"] == to_status]
    return action


async def test_submit_and_accept_say_what_stops_them_and_clear_as_work_is_done(act, people, db_session):
    case_id = await create_draft(act, people["applicant"], certificate_of_origin_numbers=["CO-B-1"])
    events_before = await db_session.scalar(select(func.count()).select_from(AuditEvent))

    # The applicant's Submit button says what's missing (the screen counts them).
    blocked = (await _action(act, people["applicant"], case_id, "submitted"))["blocked_by"]
    assert "Invoice is missing" in blocked
    assert "Certificate of origin is missing" in blocked

    # The dry run changed nothing: still a draft, no new audit rows.
    case = (await act(people["applicant"], "get", f"/cases/{case_id}")).json()
    assert case["status"]["label"] == "Draft"
    assert await db_session.scalar(select(func.count()).select_from(AuditEvent)) == events_before

    await upload_required(act, people["applicant"], case_id)
    assert (await _action(act, people["applicant"], case_id, "submitted"))["blocked_by"] == []
    assert (await submit(act, people["applicant"], case_id)).status_code == 200

    # At Records, with everything uploaded but the original not yet seen, only that is left.
    blocked = (await _action(act, people["records_officer"], case_id, "originals_received"))["blocked_by"]
    assert blocked == ["the original certificate of origin hasn't been marked as seen"]


async def test_nothing_blocks_a_ready_move(act, people):
    case_id = await _submit(act, people)
    await ready_for_records(act, people, case_id)
    assert (await _action(act, people["records_officer"], case_id, "originals_received"))["blocked_by"] == []


async def test_the_desk_sees_the_hs_code_is_needed(act, people):
    case_id = await _submit(act, people)
    await ready_for_records(act, people, case_id)
    assert (await move(act, people["records_officer"], case_id, "originals_received")).status_code == 200

    blocked = (await _action(act, people["desk"], case_id, "verified"))["blocked_by"]
    assert "the HS code hasn't been confirmed by an officer" in blocked
    assert (await confirm_hs_code(act, people, case_id)).status_code == 200
    assert (await _action(act, people["desk"], case_id, "verified"))["blocked_by"] == []


async def test_an_open_duplicate_flag_shows_as_on_hold(act, people):
    await _submit(act, people, "CO-B-DUP")
    second = await _submit(act, people, "CO-B-DUP")
    await ready_for_records(act, people, second)
    blocked = (await _action(act, people["records_officer"], second, "originals_received"))["blocked_by"]
    assert any(reason.startswith("On hold: Certificate of origin number(s) already used") for reason in blocked)


async def test_queues_leave_it_out_for_speed(act, people):
    case_id = await _submit(act, people)
    queue = (await act(people["records_officer"], "get", "/cases/queue")).json()
    [row] = [r for r in queue if r["id"] == case_id]
    assert row["available_actions"][0]["blocked_by"] is None
