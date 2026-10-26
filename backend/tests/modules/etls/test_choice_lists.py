"""Exporter countries and units are fixed lists, kept by an admin (migration 0039)."""

import pytest
from sqlalchemy import text

from tests.support import create_draft, facility_letter_form, submit, upload_required

pytestmark = pytest.mark.anyio

URL = "/etls/facility-letters"


async def test_the_form_offers_the_agreed_lists_in_order(act, people):
    response = await act(people["applicant"], "get", "/etls/form-options")
    assert response.status_code == 200, response.text
    assert response.json() == {
        "countries": [
            "Benin", "Cabo Verde", "Côte d’Ivoire", "Ghana", "Guinea", "Guinea-Bissau",
            "Liberia", "Nigeria", "Senegal", "Sierra Leone", "Togo",
        ],
        "units": ["bags", "cartons", "tonnes", "kg", "litres", "pieces"],
    }


async def test_a_value_off_the_list_is_refused_and_says_which(act, people):
    response = await act(people["applicant"], "post", URL, json={"exporter_country": "Mali", "unit": "crates"})
    assert response.status_code == 422
    detail = response.json()["detail"]
    assert "Exporter's country: 'Mali' isn't on the Ministry's list" in detail
    assert "Unit: 'crates' isn't on the Ministry's list" in detail


async def test_the_list_spelling_is_stored_whatever_the_case_typed(act, people):
    draft = (await act(people["applicant"], "post", URL, json={"exporter_country": "ghana", "unit": "TONNES"})).json()
    assert (draft["exporter_country"], draft["unit"]) == ("Ghana", "tonnes")


async def test_a_draft_may_still_leave_them_empty(act, people):
    response = await act(people["applicant"], "post", URL, json={"product": "Cement"})
    assert response.status_code == 201, response.text


async def test_changing_a_draft_is_checked_too(act, people):
    case_id = await create_draft(act, people["applicant"])
    response = await act(people["applicant"], "put", f"{URL}/{case_id}", json=facility_letter_form(unit="crates"))
    assert response.status_code == 422


async def test_a_walk_in_is_checked_before_an_account_is_made(act, people):
    response = await act(
        people["records_officer"], "post", f"{URL}/walk-in",
        json={"applicant_email": "new.importer@example.gm", "applicant_name": "New Importer", "form": {"unit": "crates"}},
    )
    assert response.status_code == 422, response.text


# --- Admins keep the lists ------------------------------------------------------


async def _lists(act, admin) -> dict:
    response = await act(admin, "get", "/etls/lists")
    assert response.status_code == 200, response.text
    return response.json()


async def test_an_admin_adds_renames_and_switches_off_entries(act, people, make_user):
    admin = await make_user("admin")
    added = await act(admin, "post", "/etls/lists/units", json={"name": "drums"})
    assert added.status_code == 201, added.text
    drums = added.json()
    assert (drums["name"], drums["active"], drums["sort_order"]) == ("drums", True, 7)  # at the end
    assert "drums" in (await act(people["applicant"], "get", "/etls/form-options")).json()["units"]

    renamed = await act(admin, "patch", f"/etls/lists/units/{drums['id']}", json={"name": "drums (200 litres)"})
    assert renamed.json()["name"] == "drums (200 litres)"

    off = await act(admin, "patch", f"/etls/lists/units/{drums['id']}", json={"active": False})
    assert off.json()["active"] is False
    assert "drums (200 litres)" not in (await act(people["applicant"], "get", "/etls/form-options")).json()["units"]
    # Still on the admin's list, to switch back on.
    assert [u["active"] for u in (await _lists(act, admin))["units"] if u["id"] == drums["id"]] == [False]


async def test_names_are_unique_ignoring_case(act, make_user):
    admin = await make_user("admin")
    response = await act(admin, "post", "/etls/lists/countries", json={"name": "ghana"})
    assert response.status_code == 422
    assert "already on the list" in response.json()["detail"]


async def test_every_change_is_in_the_audit_log(act, make_user, db_session):
    admin = await make_user("admin")
    entry = (await act(admin, "post", "/etls/lists/countries", json={"name": "Gambia (re-export)"})).json()
    await act(admin, "patch", f"/etls/lists/countries/{entry['id']}", json={"active": False})
    actions = (
        await db_session.execute(
            text("SELECT action FROM core.audit_log WHERE entity_type = 'etls_list_item' AND entity_id = :id ORDER BY id"),
            {"id": f"countries/{entry['id']}"},
        )
    ).scalars().all()
    assert actions == ["etls.list_item_added", "etls.list_item_changed"]


async def test_only_admins_may_change_the_lists(act, people):
    for who in ("applicant", "records_officer", "permanent_secretary"):
        assert (await act(people[who], "get", "/etls/lists")).status_code == 403
        assert (await act(people[who], "post", "/etls/lists/units", json={"name": "sacks"})).status_code == 403


async def test_the_app_cannot_delete_an_entry(db_session):
    with pytest.raises(Exception, match="permission denied"):
        await db_session.execute(text("DELETE FROM etls.units"))


# --- An entry switched off after the draft was saved -----------------------------


async def test_submit_is_blocked_if_an_entry_was_switched_off_since(act, people, make_user):
    case_id = await create_draft(act, people["applicant"], **facility_letter_form(unit="tonnes"))
    await upload_required(act, people["applicant"], case_id)
    admin = await make_user("admin")
    [tonnes] = [u for u in (await _lists(act, admin))["units"] if u["name"] == "tonnes"]
    await act(admin, "patch", f"/etls/lists/units/{tonnes['id']}", json={"active": False})

    case = (await act(people["applicant"], "get", f"/cases/{case_id}")).json()
    [action] = [a for a in case["available_actions"] if a["to_status"] == "submitted"]
    assert "Unit 'tonnes' is no longer on the Ministry's list: choose another" in action["blocked_by"]
    assert (await submit(act, people["applicant"], case_id)).status_code == 409
