"""Certificates of origin are valid for six months from their issue date (decided 2026-10-24).

- The desk's Verify is blocked while any certificate is more than six months past its issue date.
- At submission, a certificate that expires within 30 days gives a warning, but doesn't stop it.
"""

from datetime import date, timedelta

import pytest
from sqlalchemy import text

from app.core.dates import add_months
from app.core.workflow.delegation import today
from tests.support import (
    certificate,
    ready_to_verify,
    create_draft,
    move,
    ready_for_records,
    submit,
    upload_required,
)

pytestmark = pytest.mark.anyio


@pytest.mark.parametrize(
    "day, months, expected",
    [
        (date(2026, 10, 16), 6, date(2027, 4, 16)),
        (date(2026, 8, 31), 6, date(2027, 2, 28)),  # February has no 31st
        (date(2027, 8, 31), 6, date(2028, 2, 29)),  # ... nor a 30th, even in a leap year
        (date(2026, 4, 16), -6, date(2025, 10, 16)),
    ],
)
def test_add_months(day, months, expected):
    assert add_months(day, months) == expected


async def _draft_issued(act, people, issued_on: date) -> int:
    return await create_draft(
        act, people["applicant"], certificates_of_origin=[certificate("SN-CO-V-1", issued_on)]
    )


async def _action(act, user, case_id, to_status) -> dict:
    actions = (await act(user, "get", f"/cases/{case_id}")).json()["available_actions"]
    [action] = [a for a in actions if a["to_status"] == to_status]
    return action


async def _at_desk(act, people, case_id) -> None:
    await ready_for_records(act, people, case_id)
    assert (await move(act, people["records_officer"], case_id, "originals_received")).status_code == 200
    assert (await ready_to_verify(act, people, case_id)).status_code == 200


async def test_the_form_shows_when_each_certificate_expires(act, people):
    case_id = await _draft_issued(act, people, date(2026, 8, 31))
    [shown] = (await act(people["applicant"], "get", f"/etls/facility-letters/{case_id}")).json()["certificates_of_origin"]
    assert shown == {"number": "SN-CO-V-1", "issued_on": "2026-08-31", "expires_on": "2027-02-28"}


async def test_a_fresh_certificate_gives_no_warning_and_verifies(act, people):
    case_id = await _draft_issued(act, people, today() - timedelta(days=10))
    await upload_required(act, people["applicant"], case_id)
    assert (await _action(act, people["applicant"], case_id, "submitted"))["warnings"] == []
    await _at_desk(act, people, case_id)
    assert (await _action(act, people["desk"], case_id, "verified"))["blocked_by"] == []


async def test_submitting_warns_when_a_certificate_expires_within_30_days(act, people, db_session):
    expires = today() + timedelta(days=20)
    case_id = await _draft_issued(act, people, add_months(expires, -6))
    await upload_required(act, people["applicant"], case_id)

    submit_action = await _action(act, people["applicant"], case_id, "submitted")
    assert submit_action["blocked_by"] == []  # a warning, not a block
    [warning] = submit_action["warnings"]
    assert "SN-CO-V-1 expires on" in warning

    assert (await submit(act, people["applicant"], case_id)).status_code == 200
    # The history shows what the applicant was told when they submitted.
    row = await db_session.scalar(
        text(
            "SELECT details FROM core.audit_log WHERE entity_type = 'case' AND entity_id = :id "
            "AND action = 'case.status_changed' ORDER BY id DESC LIMIT 1"
        ),
        {"id": str(case_id)},
    )
    assert row["warnings"] == [warning]


async def test_an_expired_certificate_warns_at_submission_and_blocks_verify(act, people):
    issued = add_months(today(), -7)
    case_id = await _draft_issued(act, people, issued)
    await upload_required(act, people["applicant"], case_id)
    [warning] = (await _action(act, people["applicant"], case_id, "submitted"))["warnings"]
    assert "SN-CO-V-1 expired on" in warning
    assert (await submit(act, people["applicant"], case_id)).status_code == 200

    await _at_desk(act, people, case_id)
    blocked = (await _action(act, people["desk"], case_id, "verified"))["blocked_by"]
    assert any(reason.startswith("certificate of origin SN-CO-V-1 expired on") for reason in blocked)
    response = await move(act, people["desk"], case_id, "verified")
    assert response.status_code == 409
    assert "expired" in response.json()["detail"]


async def test_exactly_six_months_is_still_valid(act, people):
    case_id = await _draft_issued(act, people, add_months(today(), -6))
    await _at_desk(act, people, case_id)
    assert (await move(act, people["desk"], case_id, "verified")).status_code == 200


async def test_an_old_application_without_issue_dates_cannot_be_verified(act, people, db_session):
    case_id = await _draft_issued(act, people, today())
    await _at_desk(act, people, case_id)
    # As an application from before issue dates were asked would look.
    await db_session.execute(
        text("DELETE FROM etls.facility_letter_certificates WHERE case_id = :id"), {"id": case_id}
    )
    await db_session.execute(
        text(
            "INSERT INTO etls.facility_letter_certificates (case_id, number, number_normalized) "
            "VALUES (:id, 'OLD-1', 'OLD-1')"
        ),
        {"id": case_id},
    )
    blocked = (await _action(act, people["desk"], case_id, "verified"))["blocked_by"]
    assert "the issue date of certificate of origin OLD-1 isn't recorded" in blocked
