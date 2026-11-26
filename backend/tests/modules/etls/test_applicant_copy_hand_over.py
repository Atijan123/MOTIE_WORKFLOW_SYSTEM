"""Step 13b: in the office, Records prints the applicant's copy of the letter
and hands it over; the Outgoing tab lists the copies still to hand over."""

import pytest
from sqlalchemy import select

from app.core.audit.models import AuditEvent
from tests.support import (
    facility_letter_form,
    move,
    ready_for_records,
    ready_to_verify,
    send_to_gra,
    verified_case,
)

pytestmark = pytest.mark.anyio

LIST = "/etls/applicant-copies"


async def _walk_in_signed(act, people) -> int:
    """A walk-in entered by Records, taken to "signed" (not yet sent to GRA)."""
    records = people["records_officer"]
    created = await act(
        records, "post", "/etls/facility-letters/walk-in",
        # Its own certificate number: a number used twice puts the case on hold (step 6b).
        json={"applicant_email": None, "applicant_name": "Ebrima Sowe",
              "form": facility_letter_form(certificate_of_origin_numbers=["GM-WALKIN-CO-0001"])},
    )
    assert created.status_code == 201, created.text
    case_id = created.json()["case_id"]
    # Records makes the applicant's moves on a walk-in.
    await ready_for_records(act, {**people, "applicant": records}, case_id)
    assert (await move(act, records, case_id, "originals_received")).status_code == 200
    assert (await ready_to_verify(act, people, case_id)).status_code == 200
    assert (await move(act, people["desk"], case_id, "verified")).status_code == 200
    assert (await move(act, people["director"], case_id, "signed")).status_code == 200
    return case_id


async def test_records_hands_over_the_copy_once_the_letter_is_sent(act, people, db_session):
    records = people["records_officer"]
    case_id = await _walk_in_signed(act, people)
    # Not before GRA's copy is sent (the rule from step 10b).
    assert [c["case_id"] for c in (await act(records, "get", LIST)).json()] == []
    early = await act(records, "post", f"/etls/facility-letters/{case_id}/applicant-copy/handed-over")
    assert early.status_code == 409

    assert (await send_to_gra(act, people, case_id)).status_code == 200
    listed = (await act(records, "get", LIST)).json()
    assert [(c["case_id"], c["applicant_name"]) for c in listed] == [(case_id, "Ebrima Sowe")]
    # The copy itself: the stored letter.
    pdf = await act(records, "get", f"/etls/facility-letters/{case_id}/my-copy.pdf")
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")

    done = await act(records, "post", f"/etls/facility-letters/{case_id}/applicant-copy/handed-over")
    assert done.status_code == 204
    assert (await act(records, "get", LIST)).json() == []
    again = await act(records, "post", f"/etls/facility-letters/{case_id}/applicant-copy/handed-over")
    assert again.status_code == 409
    event = await db_session.scalar(select(AuditEvent).where(AuditEvent.action == "etls.applicant_copy_handed_over"))
    assert (event.entity_id, event.actor_user_id) == (str(case_id), records.id)


async def test_only_walk_ins_and_only_records(act, people):
    # An application the importer made online: they download their own copy.
    online = await verified_case(act, people)
    assert (await move(act, people["director"], online, "signed")).status_code == 200
    assert (await send_to_gra(act, people, online)).status_code == 200
    assert [c["case_id"] for c in (await act(people["records_officer"], "get", LIST)).json()] == []
    not_walk_in = await act(people["records_officer"], "post", f"/etls/facility-letters/{online}/applicant-copy/handed-over")
    assert not_walk_in.status_code == 404

    walk_in = await _walk_in_signed(act, people)
    assert (await send_to_gra(act, people, walk_in)).status_code == 200
    # The desk isn't Records: it may not act as the applicant.
    assert (await act(people["desk"], "get", LIST)).json() == []
    desk = await act(people["desk"], "post", f"/etls/facility-letters/{walk_in}/applicant-copy/handed-over")
    assert desk.status_code == 404
