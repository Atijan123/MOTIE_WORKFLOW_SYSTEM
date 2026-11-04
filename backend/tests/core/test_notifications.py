"""Emails to applicants (SCREENS.md global rules): one per status change they can
see, written to an outbox with the move, sent later by the worker."""

import subprocess
import sys

import pytest
from sqlalchemy import select, text

from app.core.notifications.models import Notification
from app.core.notifications.sender import FakeSender
from app.core.notifications.worker import MAX_ATTEMPTS, send_pending
from tests.support import (
    create_draft,
    move,
    ready_for_records,
    ready_to_verify,
    send_to_gra,
    submitted_case,
)

pytestmark = pytest.mark.anyio


async def _outbox(db_session, case_id) -> list[Notification]:
    return list(
        await db_session.scalars(select(Notification).where(Notification.case_id == case_id).order_by(Notification.id))
    )


async def test_submitting_writes_an_email_to_the_outbox(act, people, db_session):
    draft = await create_draft(act, people["applicant"])
    assert await _outbox(db_session, draft) == []  # starting a draft isn't news

    case_id = await submitted_case(act, people)
    [email] = await _outbox(db_session, case_id)
    reference = (await act(people["applicant"], "get", f"/cases/{case_id}")).json()["reference"]
    assert email.to_email == people["applicant"].email
    assert email.subject == f"{reference}: Submitted"
    assert "Bring the original certificate of origin to Records." in email.body
    assert email.sent_at is None  # the worker sends it


async def test_a_return_carries_the_message_never_the_minute(act, people, db_session):
    case_id = await submitted_case(act, people)
    response = await move(
        act,
        people["records_officer"],
        case_id,
        "returned",
        comment="Applicant has been warned before",
        applicant_message="Please upload a clearer invoice.",
    )
    assert response.status_code == 200, response.text
    email = (await _outbox(db_session, case_id))[-1]
    assert email.subject.endswith(": Returned: action needed")
    assert "Please upload a clearer invoice." in email.body
    assert "warned before" not in email.body
    assert people["records_officer"].full_name not in email.body  # no staff names


async def test_hidden_moves_and_repeated_labels_send_nothing(act, people, db_session):
    case_id = await submitted_case(act, people, certificate_of_origin_numbers=["CO-N-1"])
    await ready_for_records(act, people, case_id)
    assert (await move(act, people["records_officer"], case_id, "originals_received")).status_code == 200
    await ready_to_verify(act, people, case_id)
    assert (await move(act, people["desk"], case_id, "verified")).status_code == 200
    assert (await move(act, people["director"], case_id, "signed")).status_code == 200
    before = len(await _outbox(db_session, case_id))

    # The PS cancels the letter: invisible to the applicant, so no email.
    cancel = await move(act, people["director"], case_id, "originals_received", comment="Typo")
    assert cancel.status_code == 200, cancel.text
    assert len(await _outbox(db_session, case_id)) == before

    assert (await move(act, people["desk"], case_id, "verified")).status_code == 200
    assert (await move(act, people["director"], case_id, "signed")).status_code == 200
    assert (await send_to_gra(act, people, case_id)).status_code == 200
    subjects = [e.subject.split(": ", 1)[1] for e in await _outbox(db_session, case_id)]
    assert subjects == [
        "Submitted",
        "Originals checked",
        "Awaiting signature",
        "Letter signed",
        "Awaiting signature",
        "Letter signed",
        "Letter sent to GRA",
    ]


async def test_a_move_that_fails_leaves_no_email(act, people, db_session):
    case_id = await submitted_case(act, people)
    before = len(await _outbox(db_session, case_id))
    # Not ready (the original hasn't been seen): refused, so nothing is written.
    assert (await move(act, people["records_officer"], case_id, "originals_received")).status_code == 409
    assert len(await _outbox(db_session, case_id)) == before


async def test_the_worker_sends_each_email_once(act, people, db_session):
    case_id = await submitted_case(act, people)
    sender = FakeSender()
    # Other tests may have left committed emails behind; send everything due.
    await send_pending(db_session, sender, limit=1000)
    assert any(e.subject.endswith(": Submitted") and e.to == people["applicant"].email for e in sender.sent)
    [email] = await _outbox(db_session, case_id)
    assert email.sent_at is not None and email.attempts == 1

    again = FakeSender()
    await send_pending(db_session, again, limit=1000)
    assert not [e for e in again.sent if e.to == people["applicant"].email]


class BrokenSender:
    async def send(self, email):
        raise ConnectionError("mail server unreachable")


async def test_a_failed_send_is_retried_later_and_given_up_in_the_end(act, people, db_session):
    case_id = await submitted_case(act, people)
    await send_pending(db_session, BrokenSender(), limit=1000)
    [email] = await _outbox(db_session, case_id)
    assert email.sent_at is None
    assert email.attempts == 1
    assert "mail server unreachable" in email.last_error
    # Not due again yet: waits a minute before the second try.
    assert await db_session.scalar(text("SELECT next_attempt_at > now() FROM core.notifications WHERE id = :id"), {"id": email.id})

    # Pretend the waits have passed, until it's given up.
    for _ in range(MAX_ATTEMPTS):
        await db_session.execute(text("UPDATE core.notifications SET next_attempt_at = now() WHERE id = :id"), {"id": email.id})
        await send_pending(db_session, BrokenSender(), limit=1000)
    await db_session.refresh(email)
    assert email.attempts == MAX_ATTEMPTS
    assert email.sent_at is None


def test_the_worker_starts_on_its_own():
    # The worker runs as its own process, without the API's imports. Its
    # foreign keys must still find their tables, or saving "sent" fails
    # (found by a smoke test: NoReferencedTableError after the first email).
    check = "; ".join(
        [
            "import app.core.notifications.worker",
            "from app.core.notifications.models import Notification",
            "[fk.column for fk in Notification.__table__.foreign_keys]",
        ]
    )
    result = subprocess.run([sys.executable, "-c", check], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
