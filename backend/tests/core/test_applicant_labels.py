"""What applicants see: plain status labels, never internal step names (SCREENS.md global rules)."""

import pytest
from sqlalchemy import text

from tests.support import create_draft, move, ready_for_records, submitted_case

pytestmark = pytest.mark.anyio


async def test_every_status_of_every_workflow_has_an_applicant_label(db_session):
    # The column is NOT NULL, but an empty string would slip through it.
    missing = (
        await db_session.execute(
            text(
                "SELECT w.code, s.code FROM core.workflow_statuses s "
                "JOIN core.workflows w ON w.id = s.workflow_id WHERE btrim(s.applicant_label) = ''"
            )
        )
    ).all()
    assert missing == []


async def test_facility_letter_labels_are_the_ones_in_the_spec(db_session):
    rows = (
        await db_session.execute(
            text(
                "SELECT s.code, s.applicant_label FROM core.workflow_statuses s "
                "JOIN core.workflows w ON w.id = s.workflow_id WHERE w.code = 'etls_facility_letter'"
            )
        )
    ).all()
    assert dict(rows) == {
        "draft": "Draft",
        "returned": "Returned: action needed",
        "submitted": "Submitted",
        "originals_received": "Being verified",
        "verified": "Awaiting signature",
        "signed": "Letter signed",
        "sent_to_gra": "Letter sent to GRA",
        "rejected": "Rejected",
    }


async def test_the_applicant_sees_the_label_and_staff_see_the_code_too(act, people):
    case_id = await submitted_case(act, people)

    as_applicant = (await act(people["applicant"], "get", f"/cases/{case_id}")).json()["status"]
    assert as_applicant == {
        "code": None,
        "name": None,
        "label": "Submitted",
        "explanation": "Bring the original certificate of origin to Records.",
        "is_final": False,
        "editable": False,
    }

    as_staff = (await act(people["desk"], "get", f"/cases/{case_id}")).json()["status"]
    assert (as_staff["code"], as_staff["name"], as_staff["label"]) == (
        "submitted",
        "Submitted",
        "Submitted",
    )


async def test_the_label_follows_the_case(act, people):
    case_id = await create_draft(act, people["applicant"])
    await ready_for_records(act, people, case_id)
    assert (await move(act, people["records_officer"], case_id, "originals_received")).status_code == 200

    status = (await act(people["applicant"], "get", f"/cases/{case_id}")).json()["status"]
    assert status["label"] == "Being verified"
    letter = (await act(people["applicant"], "get", f"/etls/facility-letters/{case_id}")).json()
    assert (letter["status"], letter["status_label"]) == (None, "Being verified")


async def test_the_moves_say_how_the_timeline_describes_them(db_session):
    rows = (
        await db_session.execute(
            text(
                "SELECT x.name, x.applicant_event, x.applicant_visible FROM core.workflow_transitions x "
                "JOIN core.workflows w ON w.id = x.workflow_id WHERE w.code = 'etls_facility_letter' "
                "AND (x.applicant_event IS NOT NULL OR NOT x.applicant_visible) ORDER BY x.id"
            )
        )
    ).all()
    assert [tuple(r) for r in rows] == [
        ("Confirm originals received", "Originals checked", True),
        # Cancelling a signed letter is invisible to the applicant (SCREENS.md A2).
        ("Cancel the signed letter", None, False),
        ("Cancel the signed letter", None, False),
        ("Resubmit", "Resubmitted", True),  # 0027
    ]
