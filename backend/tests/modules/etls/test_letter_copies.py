"""Three copies of each signed letter (SCREENS.md S3): one stored file, and a
record for Records' file copy, GRA's copy and the applicant's. The applicant
may download theirs once GRA's is marked sent."""

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError

from app.modules.etls.models import FacilityLetterCopy
from tests.support import move, send_to_gra, verified_case

pytestmark = pytest.mark.anyio

URL = "/etls/facility-letters"


async def _signed(act, people, **form) -> int:
    case_id = await verified_case(act, people, **form)
    assert (await move(act, people["director"], case_id, "signed")).status_code == 200
    return case_id


async def _letters(act, people, case_id) -> list[dict]:
    response = await act(people["records_officer"], "get", f"{URL}/{case_id}/letters")
    assert response.status_code == 200, response.text
    return response.json()


async def test_signing_records_three_copies_of_one_letter(act, people, db_session):
    case_id = await _signed(act, people)
    [current] = await _letters(act, people, case_id)
    assert [(c["recipient"], c["label"], c["sent_on"]) for c in current["copies"]] == [
        ("records_file", "Records' file copy", None),
        ("gra", "GRA's copy", None),
        ("applicant", "The applicant's copy", None),
    ]
    rows = list(await db_session.scalars(select(FacilityLetterCopy).where(FacilityLetterCopy.case_id == case_id)))
    assert {r.issued_document_id for r in rows} == {current["id"]}  # all three are the one stored letter


async def test_the_applicant_downloads_their_copy_once_gras_is_sent(act, people):
    case_id = await _signed(act, people)
    applicant = people["applicant"]

    early = await act(applicant, "get", f"{URL}/{case_id}/my-copy.pdf")
    assert early.status_code == 409
    assert "sent the letter to GRA" in early.json()["detail"]
    assert (await act(applicant, "get", f"{URL}/{case_id}")).json()["letter_copy_url"] is None

    assert (await send_to_gra(act, people, case_id)).status_code == 200
    view = (await act(applicant, "get", f"{URL}/{case_id}")).json()
    assert view["letter_copy_url"] == f"{URL}/{case_id}/my-copy.pdf"
    response = await act(applicant, "get", view["letter_copy_url"])
    assert response.status_code == 200
    assert response.content.startswith(b"%PDF-")
    # The same stored file as Records', checked by its checksum.
    staff_copy = await act(people["records_officer"], "get", f"{URL}/{case_id}/letter.pdf")
    assert response.headers["X-Checksum-SHA256"] == staff_copy.headers["X-Checksum-SHA256"]

    [current] = await _letters(act, people, case_id)
    sent = {c["recipient"]: c["sent_on"] for c in current["copies"]}
    assert sent["gra"] == sent["applicant"] == current["sent_to_gra_on"] and sent["records_file"] is None


@pytest.mark.parametrize("who", ["records_officer", "director", "other_applicant"])
async def test_only_the_applicant_gets_the_applicants_copy(act, people, make_user, who):
    case_id = await _signed(act, people)
    await send_to_gra(act, people, case_id)
    user = await make_user("applicant") if who == "other_applicant" else people[who]
    assert (await act(user, "get", f"{URL}/{case_id}/my-copy.pdf")).status_code == 404
    assert (await act(user, "get", f"{URL}/{case_id}")).json().get("letter_copy_url") is None


async def test_a_cancelled_letter_s_copy_is_withdrawn_until_the_corrected_one_is_sent(act, people):
    case_id = await _signed(act, people)
    await send_to_gra(act, people, case_id)
    cancel = await move(act, people["director"], case_id, "originals_received", comment="Wrong quantity")
    assert cancel.status_code == 200, cancel.text
    assert (await act(people["applicant"], "get", f"{URL}/{case_id}/my-copy.pdf")).status_code == 409

    assert (await move(act, people["desk"], case_id, "verified")).status_code == 200
    assert (await move(act, people["director"], case_id, "signed")).status_code == 200
    letters = await _letters(act, people, case_id)
    assert [len(l["copies"]) for l in letters] == [3, 3]  # the corrected letter has its own three
    assert (await act(people["applicant"], "get", f"{URL}/{case_id}/my-copy.pdf")).status_code == 409
    await send_to_gra(act, people, case_id)
    assert (await act(people["applicant"], "get", f"{URL}/{case_id}/my-copy.pdf")).status_code == 200


async def test_copies_are_never_changed_or_removed(act, people, db_session):
    await _signed(act, people)
    for statement in (
        "UPDATE etls.facility_letter_copies SET recipient = 'gra'",
        "DELETE FROM etls.facility_letter_copies",
    ):
        with pytest.raises(DBAPIError, match="permission denied"):
            async with db_session.begin_nested():
                await db_session.execute(text(statement))
