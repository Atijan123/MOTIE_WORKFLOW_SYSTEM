"""Walk-ins (SCREENS.md global rules): Records opens an application for an
applicant who came in person, recorded as such."""

import pytest
from sqlalchemy import select

from app.core.audit.models import AuditEvent
from app.core.identity.models import User
from tests.support import create_draft, facility_letter_form, submit, upload_required

pytestmark = pytest.mark.anyio

URL = "/etls/facility-letters/walk-in"


def _walk_in(email="walkin@example.gm", name="Fatou Jallow", **form) -> dict:
    return {"applicant_email": email, "applicant_name": name, "form": facility_letter_form(**form)}


async def test_records_opens_a_draft_for_a_new_applicant(act, people, db_session):
    response = await act(people["records_officer"], "post", URL, json=_walk_in())
    assert response.status_code == 201, response.text
    case_id = response.json()["case_id"]

    # The case is the applicant's, with Records recorded as who entered it.
    applicant = await db_session.scalar(select(User).where(User.email == "walkin@example.gm"))
    assert applicant.role_codes == {"applicant"}
    case = (await act(people["records_officer"], "get", f"/cases/{case_id}")).json()
    assert (case["created_by"], case["entered_by"]) == (applicant.id, people["records_officer"].id)
    assert case["status"]["code"] == "draft"

    created = await db_session.scalar(
        select(AuditEvent).where(AuditEvent.entity_id == str(case_id), AuditEvent.action == "case.created")
    )
    assert created.actor_user_id == people["records_officer"].id
    assert created.details["walk_in_for_user_id"] == applicant.id
    account = await db_session.scalar(
        select(AuditEvent).where(AuditEvent.action == "user.created_for_walk_in", AuditEvent.entity_id == str(applicant.id))
    )
    assert account.actor_user_id == people["records_officer"].id


async def test_records_finishes_and_submits_it_for_them(act, people):
    case_id = (await act(people["records_officer"], "post", URL, json=_walk_in())).json()["case_id"]
    fixed = await act(
        people["records_officer"], "put", f"/etls/facility-letters/{case_id}", json=facility_letter_form(quantity="40")
    )
    assert fixed.status_code == 200, fixed.text
    await upload_required(act, people["records_officer"], case_id)
    response = await submit(act, people["records_officer"], case_id)
    assert response.status_code == 200, response.text
    assert response.json()["reference"].startswith("MOTIE/ETLS/FL/")

    history = (await act(people["desk"], "get", f"/cases/{case_id}/history")).json()
    [submitted] = [e for e in history if e["action"] == "case.status_changed"]
    assert submitted["actor_user_id"] == people["records_officer"].id
    assert submitted["details"]["basis"] == "applicant"
    assert submitted["details"]["for_applicant_user_id"] == response.json()["created_by"]


async def test_an_existing_applicant_gets_the_case_in_their_own_list(act, people):
    email = people["applicant"].email
    case_id = (await act(people["records_officer"], "post", URL, json=_walk_in(email=email.upper()))).json()["case_id"]
    mine = (await act(people["applicant"], "get", "/cases")).json()
    assert case_id in [c["id"] for c in mine]
    # Records sees the walk-ins they entered in their own list too.
    entered = (await act(people["records_officer"], "get", "/cases")).json()
    assert case_id in [c["id"] for c in entered]
    # And the applicant can carry on online themselves.
    await upload_required(act, people["applicant"], case_id)
    assert (await submit(act, people["applicant"], case_id)).status_code == 200


async def test_another_records_officer_can_carry_on(act, people, make_user):
    colleague = await make_user("records_officer", positions=["records_officer"])
    case_id = (await act(people["records_officer"], "post", URL, json=_walk_in())).json()["case_id"]
    await upload_required(act, colleague, case_id)
    assert (await submit(act, colleague, case_id)).status_code == 200


@pytest.mark.parametrize("who", ["desk", "permanent_secretary", "applicant"])
async def test_only_records_opens_walk_ins(act, people, db_session, who):
    response = await act(people[who], "post", URL, json=_walk_in(email=f"nobody-{who}@example.gm"))
    assert response.status_code == 403
    # Refused before any account was made.
    assert await db_session.scalar(select(User).where(User.email == f"nobody-{who}@example.gm")) is None


async def test_other_staff_cannot_submit_a_walk_in(act, people):
    case_id = (await act(people["records_officer"], "post", URL, json=_walk_in())).json()["case_id"]
    await upload_required(act, people["records_officer"], case_id)
    assert (await submit(act, people["desk"], case_id)).status_code == 403


async def test_records_cannot_submit_an_online_application(act, people):
    # Only walk-ins: an application the applicant started online is theirs to send.
    case_id = await create_draft(act, people["applicant"])
    await upload_required(act, people["applicant"], case_id)
    assert (await submit(act, people["records_officer"], case_id)).status_code == 403
    form = facility_letter_form(quantity="1")
    assert (await act(people["records_officer"], "put", f"/etls/facility-letters/{case_id}", json=form)).status_code == 403


async def test_a_staff_email_is_refused(act, people):
    response = await act(people["records_officer"], "post", URL, json=_walk_in(email=people["desk"].email))
    assert response.status_code == 403
    assert "can't apply" in response.json()["detail"]


@pytest.mark.parametrize("email", ["not-an-email", "a@b", "two@@example.gm", ""])
async def test_a_malformed_email_is_refused(act, people, email):
    assert (await act(people["records_officer"], "post", URL, json=_walk_in(email=email))).status_code == 422
