"""S12: keeping the authorised signatories list. Who may change it, what it
refuses, and that every change is in the audit log and nothing is forgotten."""

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError

from app.core.audit.models import AuditEvent
from tests.support import SIGNATORY_LIST, add_signatory

pytestmark = pytest.mark.anyio


@pytest.fixture
async def admin(make_user):
    return await make_user("officer", "signatory_admin")


async def _list(act, admin) -> dict:
    response = await act(admin, "get", "/signatories")
    assert response.status_code == 200, response.text
    return next(l for l in response.json() if l["code"] == SIGNATORY_LIST)


async def test_one_list_covers_the_facility_letter_and_the_etls_approval(act, admin):
    found = await _list(act, admin)
    assert found["absence_wording"] == "in the Director's absence"
    assert {(u["workflow"], u["position"]) for u in found["used_for"]} == {
        ("etls_facility_letter", "director_of_industry"),
        ("etls_application", "director_of_industry"),
    }


async def test_the_admin_adds_a_named_person_and_it_is_audited(act, admin, make_user, db_session):
    person = await make_user("officer")
    response = await add_signatory(act, admin, person)
    assert response.status_code == 201, response.text
    added = response.json()
    assert (added["name"], added["added_by"], added["removed_at"]) == (person.full_name, admin.full_name, None)

    found = await _list(act, admin)
    assert [m["user_id"] for m in found["current"]] == [person.id]
    event = await db_session.scalar(
        select(AuditEvent).where(AuditEvent.action == "signatory.added", AuditEvent.entity_id == str(added["id"]))
    )
    assert event.actor_user_id == admin.id
    assert event.details == {"list": SIGNATORY_LIST, "user_id": person.id, "name": person.full_name, "positions": []}


async def test_removing_keeps_the_row_with_when_and_by_whom(act, admin, make_user, db_session):
    person = await make_user("officer")
    added = (await add_signatory(act, admin, person)).json()
    response = await act(admin, "post", f"/signatories/members/{added['id']}/remove")
    assert response.status_code == 200, response.text
    assert response.json()["removed_by"] == admin.full_name

    found = await _list(act, admin)
    assert found["current"] == []
    assert [(m["id"], m["removed_by"]) for m in found["past"]] == [(added["id"], admin.full_name)]
    assert await db_session.scalar(
        select(AuditEvent.id).where(AuditEvent.action == "signatory.removed", AuditEvent.entity_id == str(added["id"]))
    )
    # Taking someone off twice is refused, and they can be put back: a new row.
    assert (await act(admin, "post", f"/signatories/members/{added['id']}/remove")).status_code == 409
    again = await add_signatory(act, admin, person)
    assert again.status_code == 201 and again.json()["id"] != added["id"]


async def test_only_the_signatory_admin_may_see_or_change_the_list(act, people, make_user):
    person = await make_user("officer")
    director = people["director"]
    assert (await act(director, "get", "/signatories")).status_code == 403
    assert (await act(director, "get", "/signatories/candidates")).status_code == 403
    assert (await add_signatory(act, director, person)).status_code == 403


@pytest.mark.parametrize("who", ["self", "applicant", "twice"])
async def test_what_the_list_refuses(act, admin, make_user, who):
    person = {"self": admin, "applicant": await make_user("applicant")}.get(who) or await make_user("officer")
    if who == "twice":
        assert (await add_signatory(act, admin, person)).status_code == 201
    response = await add_signatory(act, admin, person)
    assert response.status_code == 422, response.text


async def test_candidates_are_active_staff_only(act, admin, make_user):
    applicant = await make_user("applicant")
    officer = await make_user("officer")
    ids = {c["user_id"] for c in (await act(admin, "get", "/signatories/candidates")).json()}
    assert officer.id in ids and applicant.id not in ids


async def test_an_unknown_list_or_entry_is_not_found(act, admin, make_user):
    person = await make_user("officer")
    response = await act(admin, "post", "/signatories/no_such_list/members", json={"user_id": person.id})
    assert response.status_code == 404
    assert (await act(admin, "post", "/signatories/members/999999/remove")).status_code == 404


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE core.authorised_signatories SET removed_at = NULL, removed_by = NULL",  # un-remove
        "UPDATE core.authorised_signatories SET added_at = now() - interval '1 year'",  # back-date
    ],
    ids=["un-remove", "back-date"],
)
async def test_the_database_refuses_to_rewrite_the_record(act, admin, make_user, db_session, statement):
    person = await make_user("officer")
    added = (await add_signatory(act, admin, person)).json()
    await act(admin, "post", f"/signatories/members/{added['id']}/remove")
    with pytest.raises(DBAPIError, match="permission denied|can't be changed"):
        async with db_session.begin_nested():
            await db_session.execute(text(statement))


async def test_the_app_can_neither_delete_entries_nor_change_the_rules(db_session):
    for statement in (
        "DELETE FROM core.authorised_signatories",
        "UPDATE core.signatory_rules SET list_id = list_id",
        "INSERT INTO core.signatory_lists (code, name, absence_wording) VALUES ('x', 'x', 'x')",
    ):
        with pytest.raises(DBAPIError, match="permission denied"):
            async with db_session.begin_nested():
                await db_session.execute(text(statement))
