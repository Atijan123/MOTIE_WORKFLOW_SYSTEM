"""Who signs a facility letter (SCREENS.md S3, S12), and the Director's sign-and-assign
on an ETLS approval (S5):

- the Director of Industry and Investment signs;
- while every Director is recorded absent, anyone on the authorised signatories
  list may, instead of the succession order; the first to act claims it;
- a cement letter (HS heading 2523, as the desk confirms it): only the
  Minister or the PS, in their own right.
"""

from datetime import timedelta

import pytest
from sqlalchemy import select

from app.core.audit.models import AuditEvent
from app.core.documents import issued
from app.core.workflow.models import Case
from app.core.workflow.delegation import today
from app.modules.etls import letter
from tests.support import (
    CEMENT,
    add_signatory,
    create_draft,
    move,
    open_case,
    ready_for_records,
    ready_to_verify,
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


# --- An ordinary letter: the Director signs -----------------------------------


async def test_the_director_signs_for_the_ps_and_the_ps_no_longer_does(act, people, db_session):
    case_id = await verified_case(act, people)
    assert case_id in await _queue_ids(act, people["director"])
    assert case_id not in await _queue_ids(act, people["permanent_secretary"])
    assert (await move(act, people["permanent_secretary"], case_id, "signed")).status_code == 403
    assert (await move(act, people["director"], case_id, "signed")).status_code == 200

    fields = await letter.build_fields(db_session, case_id, await _signing_event(db_session, case_id))
    assert (fields.signature_name, fields.signature_note, fields.signature_title) == (
        people["director"].full_name,
        "",  # left out of the letter
        "For: Permanent Secretary",
    )


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


async def test_a_signatory_signs_and_the_record_and_letter_name_them(act, people, signers, db_session):
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

    fields = await letter.build_fields(db_session, case_id, event)
    assert (fields.signature_name, fields.signature_note, fields.signature_title) == (
        signer.full_name,
        "In the Director's absence",
        "For: Permanent Secretary",
    )
    stored = await issued.get_current(db_session, case_id, letter.KIND)
    assert stored.issued_by == signer.id
    pdf = letter.render_pdf(fields, compress=False).decode("latin-1")
    for expected in (signer.full_name, "In the Director's absence", "For: Permanent Secretary"):
        assert expected in pdf, expected

    # The case's history says so too.
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


async def test_the_signatory_can_also_return_to_the_desk_and_cancel(act, people, signers):
    case_id = await verified_case(act, people)
    await record_absence(act, people["director"])
    actions = {a["to_status"] for a in (await act(signers["first"], "get", f"/cases/{case_id}")).json()["available_actions"]}
    assert actions == {"signed", "originals_received"}  # sign, or return to the desk
    await move(act, signers["first"], case_id, "signed")
    cancel = await move(act, signers["second"], case_id, "originals_received", comment="Wrong HS code")
    assert cancel.status_code == 200, cancel.text


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


# --- Cement: only the Minister or the PS ---------------------------------------


async def test_a_cement_letter_is_the_minister_s_or_the_ps_s(act, people):
    case_id = await verified_case(act, people, hs_code=CEMENT)
    assert case_id not in await _queue_ids(act, people["director"])
    assert (await move(act, people["director"], case_id, "signed")).status_code == 403
    for who in ("minister", "permanent_secretary"):
        assert case_id in await _queue_ids(act, people[who])
        assert await _can(act, people[who], case_id, "signed")
    assert (await move(act, people["permanent_secretary"], case_id, "signed")).status_code == 200


async def test_the_minister_signs_cement_in_their_own_right(act, people, db_session):
    case_id = await verified_case(act, people, hs_code=CEMENT)
    assert (await move(act, people["minister"], case_id, "signed")).status_code == 200
    event = await _signing_event(db_session, case_id)
    assert (event.details["basis"], event.details["as_position"]) == ("own", "minister")
    fields = await letter.build_fields(db_session, case_id, event)
    assert (fields.signature_name, fields.signature_title) == (people["minister"].full_name, "Minister")


async def test_nobody_stands_in_for_cement(act, people, signers):
    case_id = await verified_case(act, people, hs_code=CEMENT)
    # Both away: the DPS (next in the PS's line) still may not, nor may a
    # signatory while the Director is away too.
    for who in ("minister", "permanent_secretary", "director"):
        await record_absence(act, people[who])
    for person in (people["dps"], signers["first"]):
        assert case_id not in await _queue_ids(act, person)
        assert (await move(act, person, case_id, "signed")).status_code == 403
    # An absent PS may still sign in their own right (as any absent holder may).
    assert (await move(act, people["permanent_secretary"], case_id, "signed")).status_code == 200


async def test_the_declared_code_does_not_decide_it(act, people):
    """The applicant said cement, the desk confirmed roofing sheets: the Director signs."""
    case_id = await create_draft(act, people["applicant"], hs_code=CEMENT)
    await ready_for_records(act, people, case_id)
    await move(act, people["records_officer"], case_id, "originals_received")
    await ready_to_verify(act, people, case_id, "7210.49")
    assert (await move(act, people["desk"], case_id, "verified")).status_code == 200
    assert await _can(act, people["director"], case_id, "signed")
    assert not await _can(act, people["permanent_secretary"], case_id, "signed")


async def test_the_preview_shows_whoever_will_sign(act, people, signers, db_session):
    ordinary = await verified_case(act, people)
    cement = await verified_case(act, people, hs_code=CEMENT, certificate_of_origin_numbers=["NG-CO-1"])
    await record_absence(act, people["director"])

    async def block(case_id, user):
        fields = await letter.preview_fields(db_session, await db_session.get(Case, case_id), user)
        return fields.signature_name, fields.signature_note, fields.signature_title

    assert await block(ordinary, signers["first"]) == (
        signers["first"].full_name,
        "In the Director's absence",
        "For: Permanent Secretary",
    )
    # Records may not sign: the cement letter as the PS would sign it, no name.
    assert await block(cement, people["records_officer"]) == ("", "", "Permanent Secretary")
    response = await act(signers["first"], "get", f"/etls/facility-letters/{ordinary}/letter-preview.pdf")
    assert response.status_code == 200 and response.content.startswith(b"%PDF-")


async def test_records_still_dispatches_a_letter_a_signatory_signed(act, people, signers):
    case_id = await verified_case(act, people)
    await record_absence(act, people["director"])
    await move(act, signers["first"], case_id, "signed")
    assert (await send_to_gra(act, people, case_id)).status_code == 200


# --- The ETLS approval: the Director's sign and assign (S5) ----------------------


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
