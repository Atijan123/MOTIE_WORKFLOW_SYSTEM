"""The acting banner (GET /acting) and the absences screen S11 (GET /acting/for-me,
GET /absences/current, GET /acting/options)."""

from datetime import timedelta

import pytest

from app.core.workflow.delegation import today
from tests.support import add_signatory

pytestmark = pytest.mark.anyio


def _days(n: int) -> str:
    return (today() + timedelta(days=n)).isoformat()


async def _away(act, person, reason=None, start=0, end=3):
    body = {"starts_on": _days(start), "ends_on": _days(end)}
    if reason:
        body["reason"] = reason
    response = await act(person, "post", "/absences", json=body)
    assert response.status_code == 201, response.text
    return response.json()


async def _acting(act, person) -> list[dict]:
    response = await act(person, "get", "/acting")
    assert response.status_code == 200, response.text
    return response.json()


# --- The banner: what am I acting for? -----------------------------------------


async def test_nobody_away_means_no_banner(act, people):
    assert await _acting(act, people["dps"]) == []
    assert await _acting(act, people["applicant"]) == []


async def test_the_dps_acting_for_an_absent_ps_in_every_workflow(act, people):
    await _away(act, people["permanent_secretary"])
    assert await _acting(act, people["dps"]) == [
        {
            "position": "permanent_secretary",
            "title": "Permanent Secretary",
            "basis": "succession",
            "workflows": None,  # the PS's line applies to every workflow
            "absences": [
                {"person": people["permanent_secretary"].full_name, "starts_on": _days(0), "ends_on": _days(3)}
            ],
            "delegation_starts_on": None,
            "delegation_ends_on": None,
            "in_absence": None,
        }
    ]


async def test_the_director_has_signatories_not_a_stand_in_post(act, people, make_user):
    admin, signer = await make_user("officer", "signatory_admin"), await make_user("officer")
    assert (await add_signatory(act, admin, signer)).status_code == 201
    await _away(act, people["director"])
    assert await _acting(act, people["dps"]) == []  # the DPS no longer acts for the Director
    [banner] = await _acting(act, signer)
    assert (banner["position"], banner["basis"], banner["in_absence"]) == (
        "director_of_industry",
        "signatory",
        "in the Director's absence",
    )
    # Both services with a list (null when that is every service there is).
    assert banner["workflows"] is None or set(banner["workflows"]) == {"etls_application", "etls_facility_letter"}
    assert banner["absences"][0]["person"] == people["director"].full_name


async def test_acting_by_delegation(act, people):
    response = await act(
        people["minister"], "post", "/delegations",
        json={
            "from_position": "minister",
            "to_position": "permanent_secretary",
            "starts_on": _days(0),
            "ends_on": _days(5),
            "workflow": "etls_application",
        },
    )
    assert response.status_code == 201, response.text
    [banner] = await _acting(act, people["permanent_secretary"])
    assert (banner["position"], banner["basis"], banner["workflows"]) == ("minister", "delegation", ["etls_application"])
    assert (banner["delegation_starts_on"], banner["delegation_ends_on"]) == (_days(0), _days(5))


async def test_a_future_absence_shows_no_banner_yet(act, people):
    await _away(act, people["permanent_secretary"], start=2, end=4)
    assert await _acting(act, people["dps"]) == []


# --- S11: who acts for me, and who is away -------------------------------------


async def test_who_acts_for_my_posts(act, people, make_user):
    admin, signer = await make_user("officer", "signatory_admin"), await make_user("officer")
    assert (await add_signatory(act, admin, signer)).status_code == 201
    response = await act(people["director"], "get", "/acting/for-me")
    assert response.status_code == 200
    [mine] = response.json()
    assert mine["position"] == "director_of_industry"
    assert mine["delegations"] == []
    # The Director's step goes to the authorised signatories list in both services.
    lines = {line["workflow"]: line for line in mine["succession"]}
    assert set(lines) == {"etls_application", "etls_facility_letter"}
    for line in lines.values():
        assert line["line"] == [] and signer.full_name in line["signatories"]


async def test_who_acts_while_the_director_is_away_is_the_list(act, people, make_user):
    admin, signer = await make_user("officer", "signatory_admin"), await make_user("officer")
    assert (await add_signatory(act, admin, signer)).status_code == 201
    absence = await _away(act, people["director"])
    row = await _row(act, people["desk"], absence["id"])
    [listed] = [w for w in row["who_acts"] if w["basis"] == "signatory"]
    assert listed["position"] == "director_absence"
    assert listed["title"] == "Authorised signatories in the Director's absence"
    assert signer.full_name in listed["holders"]
    assert listed["workflows"] is None or set(listed["workflows"]) == {"etls_application", "etls_facility_letter"}


async def test_my_delegations_are_listed_with_their_id(act, people):
    created = await act(
        people["permanent_secretary"], "post", "/delegations",
        json={"from_position": "permanent_secretary", "to_position": "dps_admin_finance",
              "starts_on": _days(1), "ends_on": _days(2)},
    )
    assert created.status_code == 201, created.text
    [mine] = (await act(people["permanent_secretary"], "get", "/acting/for-me")).json()
    [delegation] = mine["delegations"]
    assert delegation["id"] == created.json()["id"]  # so S11 can offer "revoke"
    assert delegation["to_position"] == "dps_admin_finance"
    # The PS's line covers every workflow.
    assert {line["workflow"] for line in mine["succession"]} == {"etls_application", "etls_facility_letter"}


async def test_staff_see_who_is_away_but_not_why(act, people, make_user):
    absence = await _away(act, people["permanent_secretary"], reason="Medical appointment")

    seen = (await act(people["desk"], "get", "/absences/current")).json()
    [row] = [r for r in seen if r["id"] == absence["id"]]
    assert row["person"] == people["permanent_secretary"].full_name
    assert row["posts"] == ["Permanent Secretary"]
    assert row["reason"] is None  # can be personal

    # The person themselves and a recorder see the reason.
    own = (await act(people["permanent_secretary"], "get", "/absences/current")).json()
    assert [r["reason"] for r in own if r["id"] == absence["id"]] == ["Medical appointment"]
    recorder = await make_user("officer", "absence_recorder")
    theirs = (await act(recorder, "get", "/absences/current")).json()
    assert [r["reason"] for r in theirs if r["id"] == absence["id"]] == ["Medical appointment"]


async def test_cancelled_absences_drop_off_and_applicants_cannot_look(act, people):
    absence = await _away(act, people["permanent_secretary"])
    assert (await act(people["permanent_secretary"], "post", f"/absences/{absence['id']}/cancel")).status_code == 200
    seen = (await act(people["desk"], "get", "/absences/current")).json()
    assert absence["id"] not in [r["id"] for r in seen]
    assert (await act(people["applicant"], "get", "/absences/current")).status_code == 403


async def test_only_the_person_and_recorders_may_cancel_an_absence(act, people, make_user):
    absence = await _away(act, people["permanent_secretary"])

    def may_cancel(rows):
        return [r["may_cancel"] for r in rows if r["id"] == absence["id"]]

    assert may_cancel((await act(people["permanent_secretary"], "get", "/absences/current")).json()) == [True]
    assert may_cancel((await act(people["desk"], "get", "/absences/current")).json()) == [False]
    recorder = await make_user("officer", "absence_recorder")
    assert may_cancel((await act(recorder, "get", "/absences/current")).json()) == [True]
    # And the flag says what the API does: the desk officer's cancel is refused.
    assert (await act(people["desk"], "post", f"/absences/{absence['id']}/cancel")).status_code == 404


# --- What the S11 forms pick from ----------------------------------------------


async def test_the_options_list_posts_with_their_holders_and_the_workflows(act, people):
    response = await act(people["desk"], "get", "/acting/options")
    assert response.status_code == 200, response.text
    options = response.json()
    posts = {p["code"]: p for p in options["posts"]}
    assert posts["permanent_secretary"]["title"] == "Permanent Secretary"
    assert posts["permanent_secretary"]["holders"] == [
        {"user_id": people["permanent_secretary"].id, "name": people["permanent_secretary"].full_name}
    ]
    titles = [p["title"] for p in options["posts"]]
    assert titles == sorted(titles)  # for a select box
    assert {"etls_facility_letter", "etls_application"} <= {w["code"] for w in options["workflows"]}


async def test_applicants_cannot_list_the_posts(act, people):
    assert (await act(people["applicant"], "get", "/acting/options")).status_code == 403


# --- Who acts, and who recorded it (the S11 list's columns) ---------------------


async def _row(act, viewer, absence_id) -> dict:
    rows = (await act(viewer, "get", "/absences/current")).json()
    [row] = [r for r in rows if r["id"] == absence_id]
    return row


async def test_the_list_says_who_acts_by_succession_and_who_recorded_it(act, people):
    absence = await _away(act, people["permanent_secretary"])
    row = await _row(act, people["desk"], absence["id"])
    assert row["who_acts"] == [
        {
            "position": "dps_admin_finance",
            "title": "Deputy Permanent Secretary, Administration and Finance",
            "holders": [people["dps"].full_name],
            "basis": "succession",
            "workflows": None,  # the PS's line covers every service
        }
    ]
    assert (row["recorded_by"], row["recorded_by_self"]) == (people["permanent_secretary"].full_name, True)


async def test_a_delegation_comes_before_the_succession_order(act, people):
    response = await act(
        people["minister"], "post", "/delegations",
        json={
            "from_position": "minister",
            "to_position": "permanent_secretary",
            "starts_on": _days(0),
            "ends_on": _days(3),
            "workflow": "etls_application",
        },
    )
    assert response.status_code == 201, response.text
    absence = await _away(act, people["minister"])
    row = await _row(act, people["desk"], absence["id"])
    delegated = [w for w in row["who_acts"] if w["basis"] == "delegation"]
    assert delegated == [
        {
            "position": "permanent_secretary",
            "title": "Permanent Secretary",
            "holders": [people["permanent_secretary"].full_name],
            "basis": "delegation",
            "workflows": ["etls_application"],  # only that service; the others follow the succession order
        }
    ]


async def test_a_stand_in_who_is_away_too_is_skipped(act, people):
    await _away(act, people["dps"])
    absence = await _away(act, people["permanent_secretary"])
    row = await _row(act, people["desk"], absence["id"])
    assert "dps_admin_finance" not in [w["position"] for w in row["who_acts"]]


async def test_who_acts_is_worked_out_for_the_first_day_of_a_later_absence(act, people):
    await _away(act, people["dps"], start=0, end=0)  # back tomorrow
    absence = await _away(act, people["permanent_secretary"], start=2, end=4)
    row = await _row(act, people["desk"], absence["id"])
    assert [w["position"] for w in row["who_acts"]] == ["dps_admin_finance"]


async def test_an_absence_entered_by_a_recorder_says_so(act, people, make_user):
    recorder = await make_user("officer", "absence_recorder")
    response = await act(
        recorder, "post", "/absences",
        json={"user_id": people["director"].id, "starts_on": _days(1), "ends_on": _days(2)},
    )
    assert response.status_code == 201, response.text
    row = await _row(act, people["desk"], response.json()["id"])
    assert (row["recorded_by"], row["recorded_by_self"]) == (recorder.full_name, False)
