"""Who signs a facility letter (SCREENS.md S3, S12), and the Director's sign-and-assign
on an ETLS approval (S5):

- the Director of Industry and Investment signs, "For: Permanent Secretary";
- while every Director is recorded absent, anyone on the authorised signatories
  list may, instead of the succession order; the first to act claims it;
- every letter, cement included, follows that one flow;
- a signed letter is cancelled by the Director, or by the officer who signed it.
"""

from datetime import timedelta

import pytest
from sqlalchemy import select

from app.core.audit.models import AuditEvent
from app.core.documents import issued
from app.core.workflow.delegation import today
from app.core.workflow.models import Case
from app.modules.etls import letter
from tests.support import (
    CEMENT,
    add_signatory,
    move,
    open_case,
    record_absence,
    send_to_gra,
    verified_case,
)

pytestmark = pytest.mark.anyio


@pytest.fixture
async def signers(make_user, act):
    """The Director's office's admin and two people on the list, neither holding a post."""
    admin = await make_user("officer", "signatory_admin")
    first, second = await make_user("officer"), await make_user("officer")
    for person in (first, second):
        assert (await add_signatory(act, admin, person)).status_code == 201
    return {"admin": admin, "first": first, "second": second}


async def _can(act, user, case_id, to_status) -> bool:
    actions = (await act(user, "get", f"/cases/{case_id}")).json()["available_actions"]
    return any(a["to_status"] == to_status for a in actions)


async def _queue_ids(act, user) -> set[int]:
    return {c["id"] for c in (await act(user, "get", "/cases/queue")).json()}


async def _signing_event(db_session, case_id) -> AuditEvent:
    events = await db_session.scalars(
        select(AuditEvent).where(AuditEvent.entity_id == str(case_id), AuditEvent.action == "case.status_changed")
    )
    return [e for e in events if e.details["to"] == "signed"][-1]


async def _cancel(act, user, case_id):
    return await move(act, user, case_id, "originals_received", comment="Wrong quantity")


# --- The Director signs ---------------------------------------------------------


async def test_the_director_signs_for_the_ps_and_the_ps_no_longer_does(act, people, db_session):
    case_id = await verified_case(act, people)
    assert case_id in await _queue_ids(act, people["director"])
    assert case_id not in await _queue_ids(act, people["permanent_secretary"])
    assert (await move(act, people["permanent_secretary"], case_id, "signed")).status_code == 403
    assert (await move(act, people["director"], case_id, "signed")).status_code == 200

    fields = await letter.build_fields(db_session, case_id, await _signing_event(db_session, case_id))
    assert (fields.signature_name, fields.signature_title) == (people["director"].full_name, "For: Permanent Secretary")
    assert (await issued.get_current(db_session, case_id, letter.KIND)).signature_note is None


async def test_a_cement_letter_follows_the_same_flow(act, people, signers):
    """No special signers for cement (removed in 0041): only the receipt differs."""
    case_id = await verified_case(act, people, hs_code=CEMENT)  # uploads the receipt the code calls for
    assert case_id in await _queue_ids(act, people["director"])
    for who in ("minister", "permanent_secretary"):
        assert case_id not in await _queue_ids(act, people[who])
        assert (await move(act, people[who], case_id, "signed")).status_code == 403
    await record_absence(act, people["director"])
    assert (await move(act, signers["first"], case_id, "signed")).status_code == 200


# --- While the Director is away: the signatories list -----------------------------


async def test_signatories_have_nothing_while_the_director_is_at_work(act, people, signers):
    case_id = await verified_case(act, people)
    assert case_id not in await _queue_ids(act, signers["first"])
    assert (await move(act, signers["first"], case_id, "signed")).status_code == 403


async def test_while_the_director_is_away_every_signatory_sees_it_and_the_dps_does_not(act, people, signers):
    case_id = await verified_case(act, people)
    assert (await record_absence(act, people["director"])).status_code == 201

    for person in (signers["first"], signers["second"]):
        assert case_id in await _queue_ids(act, person)
        assert await _can(act, person, case_id, "signed")
    # The succession step "DPS Admin & Finance acts for the Director" is gone.
    assert case_id not in await _queue_ids(act, people["dps"])
    assert (await move(act, people["dps"], case_id, "signed")).status_code == 403


async def test_a_signatory_signs_and_only_the_record_says_in_the_directors_absence(act, people, signers, db_session):
    case_id = await verified_case(act, people)
    await record_absence(act, people["director"])
    signer = signers["first"]
    response = await move(act, signer, case_id, "signed")
    assert response.status_code == 200, response.text

    event = await _signing_event(db_session, case_id)
    assert event.actor_user_id == signer.id
    assert event.details["basis"] == "signatory"
    assert event.details["on_behalf_of"] == "director_of_industry"
    assert event.details["as_position"] is None  # a named person, not a post
    assert event.details["signatory_name"] == signer.full_name
    assert event.details["in_absence"] == "in the Director's absence"
    assert event.details["absence_ids"]  # the Director's absence it relied on

    # The printed letter: the name and "For: Permanent Secretary", as the Ministry's letters are.
    fields = await letter.build_fields(db_session, case_id, event)
    assert (fields.signature_name, fields.signature_title) == (signer.full_name, "For: Permanent Secretary")
    pdf = letter.render_pdf(fields, compress=False).decode("latin-1")
    assert signer.full_name in pdf and "For: Permanent Secretary" in pdf
    assert "absence" not in pdf
    # The stored letter keeps why they could sign.
    stored = await issued.get_current(db_session, case_id, letter.KIND)
    assert (stored.issued_by, stored.signature_note) == (signer.id, "in the Director's absence")

    history = (await act(people["records_officer"], "get", f"/cases/{case_id}/history")).json()
    signed = next(h for h in history if h["details"].get("to") == "signed")
    assert signed["actor_name"] == signer.full_name
    assert signed["acting_for"]["basis"] == "signatory"
    assert signed["acting_for"]["in_absence"] == "in the Director's absence"
    assert signed["acting_for"]["absences"][0]["person"] == people["director"].full_name


async def test_once_one_signatory_has_signed_the_other_cannot(act, people, signers):
    case_id = await verified_case(act, people)
    await record_absence(act, people["director"])
    assert (await move(act, signers["first"], case_id, "signed")).status_code == 200
    assert case_id not in await _queue_ids(act, signers["second"])
    second = await move(act, signers["second"], case_id, "signed")
    assert second.status_code == 409
    assert "someone may have just acted on it" in second.json()["detail"]


async def test_a_removed_signatory_cannot_sign(act, people, signers):
    case_id = await verified_case(act, people)
    await record_absence(act, people["director"])
    lst = next(l for l in (await act(signers["admin"], "get", "/signatories")).json() if l["code"] == "director_absence")
    entry = next(m for m in lst["current"] if m["user_id"] == signers["first"].id)
    assert (await act(signers["admin"], "post", f"/signatories/members/{entry['id']}/remove")).status_code == 200
    assert not await _can(act, signers["first"], case_id, "signed")
    assert (await move(act, signers["first"], case_id, "signed")).status_code == 403


async def test_a_signatory_who_is_away_is_skipped(act, people, signers, make_user):
    """Like a successor post whose holders are all away. [CONFIRM]"""
    case_id = await verified_case(act, people)
    officer = await make_user("officer", positions=["industry_officer"])  # an absence needs a post
    assert (await add_signatory(act, signers["admin"], officer)).status_code == 201
    await record_absence(act, people["director"])
    await record_absence(act, officer)
    assert not await _can(act, officer, case_id, "signed")
    assert await _can(act, signers["first"], case_id, "signed")


async def test_the_director_can_still_delegate_the_signing(act, people):
    """A delegation is the Director's own choice and still comes first; the list
    replaces only the succession order. [CONFIRM]"""
    case_id = await verified_case(act, people)
    response = await act(
        people["director"],
        "post",
        "/delegations",
        json={
            "from_position": "director_of_industry",
            "to_position": "dps_admin_finance",
            "starts_on": today().isoformat(),
            "ends_on": (today() + timedelta(days=2)).isoformat(),
        },
    )
    assert response.status_code == 201, response.text
    assert (await move(act, people["dps"], case_id, "signed")).status_code == 200


# --- Returning and cancelling -------------------------------------------------


async def test_any_signatory_may_return_a_letter_nobody_has_signed(act, people, signers):
    case_id = await verified_case(act, people)
    await record_absence(act, people["director"])
    for person in (signers["first"], signers["second"]):
        assert await _can(act, person, case_id, "originals_received")
    response = await move(act, signers["second"], case_id, "originals_received", comment="Check the quantity")
    assert response.status_code == 200, response.text


async def test_only_the_officer_who_signed_may_cancel_among_the_signatories(act, people, signers):
    """[CONFIRM] Cancel and reissue: the Director, or the officer who signed that letter."""
    case_id = await verified_case(act, people)
    await record_absence(act, people["director"])
    assert (await move(act, signers["first"], case_id, "signed")).status_code == 200

    assert not await _can(act, signers["second"], case_id, "originals_received")
    assert (await _cancel(act, signers["second"], case_id)).status_code == 403
    assert await _can(act, signers["first"], case_id, "originals_received")
    assert (await _cancel(act, signers["first"], case_id)).status_code == 200


async def test_the_director_may_cancel_a_letter_a_signatory_signed(act, people, signers):
    case_id = await verified_case(act, people)
    absence = (await record_absence(act, people["director"])).json()
    assert (await move(act, signers["first"], case_id, "signed")).status_code == 200
    assert (await act(people["director"], "post", f"/absences/{absence['id']}/cancel")).status_code == 200
    assert (await _cancel(act, people["director"], case_id)).status_code == 200


async def test_a_delegate_may_cancel_only_a_letter_they_signed(act, people):
    case_id = await verified_case(act, people)
    assert (await move(act, people["director"], case_id, "signed")).status_code == 200
    response = await act(
        people["director"],
        "post",
        "/delegations",
        json={
            "from_position": "director_of_industry",
            "to_position": "dps_admin_finance",
            "starts_on": today().isoformat(),
            "ends_on": (today() + timedelta(days=2)).isoformat(),
        },
    )
    assert response.status_code == 201, response.text
    assert (await _cancel(act, people["dps"], case_id)).status_code == 403  # the Director signed it


# --- The preview, dispatch, and the ETLS approval -----------------------------


async def test_the_preview_shows_whoever_will_sign(act, people, signers, db_session):
    case_id = await verified_case(act, people)
    await record_absence(act, people["director"])

    async def block(user):
        fields = await letter.preview_fields(db_session, await db_session.get(Case, case_id), user)
        return fields.signature_name, fields.signature_title

    assert await block(signers["first"]) == (signers["first"].full_name, "For: Permanent Secretary")
    assert await block(people["records_officer"]) == ("", "For: Permanent Secretary")  # may not sign: no name
    response = await act(signers["first"], "get", f"/etls/facility-letters/{case_id}/letter-preview.pdf")
    assert response.status_code == 200 and response.content.startswith(b"%PDF-")


async def test_records_still_dispatches_a_letter_a_signatory_signed(act, people, signers):
    case_id = await verified_case(act, people)
    await record_absence(act, people["director"])
    await move(act, signers["first"], case_id, "signed")
    assert (await send_to_gra(act, people, case_id)).status_code == 200


async def _with_director(act, people) -> int:
    case_id = (await open_case(act, people["applicant"]))["id"]
    for who, to_status in [
        ("records_officer", "with_minister"),
        ("minister", "with_ps"),
        ("permanent_secretary", "with_director"),
    ]:
        assert (await move(act, people[who], case_id, to_status)).status_code == 200
    return case_id


async def test_sign_and_assign_goes_by_the_same_list(act, people, signers, db_session):
    case_id = await _with_director(act, people)
    assert (await move(act, signers["first"], case_id, "with_officer")).status_code == 403

    await record_absence(act, people["director"])
    assert (await move(act, people["dps"], case_id, "with_officer")).status_code == 403
    assert case_id in await _queue_ids(act, signers["second"])
    assert (await move(act, signers["second"], case_id, "with_officer")).status_code == 200
    event = await db_session.scalar(
        select(AuditEvent)
        .where(AuditEvent.entity_id == str(case_id), AuditEvent.action == "case.status_changed")
        .order_by(AuditEvent.id.desc())
        .limit(1)
    )
    assert (event.details["basis"], event.details["in_absence"]) == ("signatory", "in the Director's absence")
