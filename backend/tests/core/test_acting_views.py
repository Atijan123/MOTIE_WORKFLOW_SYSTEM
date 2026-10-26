"""The acting banner (GET /acting) and the absences screen S11 (GET /acting/for-me,
GET /absences/current, GET /acting/options)."""

from datetime import timedelta

import pytest

from app.core.workflow.delegation import today

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
        }
    ]


async def test_the_directors_stand_in_is_for_etls_approvals_only(act, people):
    await _away(act, people["director"])
    [banner] = await _acting(act, people["dps"])
    assert banner["position"] == "director_of_industry"
    assert banner["workflows"] == ["etls_application"]


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


async def test_who_acts_for_my_posts(act, people):
    response = await act(people["director"], "get", "/acting/for-me")
    assert response.status_code == 200
    [mine] = response.json()
    assert mine["position"] == "director_of_industry"
    assert mine["delegations"] == []
    # The Director's stand-in is for ETLS approvals only; no line for facility letters.
    assert [line["workflow"] for line in mine["succession"]] == ["etls_application"]
    [stand_in] = mine["succession"][0]["line"]
    assert stand_in["position"] == "dps_admin_finance"
    assert people["dps"].full_name in stand_in["holders"]


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
