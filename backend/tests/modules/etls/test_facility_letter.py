"""ETLS facility letter: the workflow definition, and submitting the form."""

import pytest
from sqlalchemy import text

from tests.support import (
    certificate,
    confirm_hs_code,
    facility_letter_form,
    move,
    ready_for_records,
    submit,
    upload_required,
)

pytestmark = pytest.mark.anyio

# The route as the Ministry gave it. [CONFIRM] who reviews between desk and PS,
# who sends to GRA and closes, and who rejects.
ROUTE = [
    ("records_officer", "originals_received"),
    ("desk", "verified"),
    ("permanent_secretary", "signed"),
    ("desk", "sent_to_gra"),
    ("desk", "closed"),
]


async def _submit(act, applicant, **changes):
    return await act(applicant, "post", "/etls/facility-letters", json=facility_letter_form(**changes))


async def test_facility_letter_workflow_is_seeded(db_session):
    rows = (
        await db_session.execute(
            text(
                "SELECT f.code, t.code, p.code FROM core.workflow_transitions x "
                "JOIN core.workflows w ON w.id = x.workflow_id "
                "JOIN core.workflow_statuses f ON f.id = x.from_status_id "
                "JOIN core.workflow_statuses t ON t.id = x.to_status_id "
                "LEFT JOIN core.positions p ON p.id = x.required_position_id "
                "WHERE w.code = 'etls_facility_letter'"
            )
        )
    ).all()
    assert {tuple(r) for r in rows} == {
        ("draft", "submitted", None),  # the applicant's own move (0026)
        # Returns and the applicant's resubmission (0027).
        ("submitted", "returned", "records_officer"),
        ("originals_received", "returned", "etls_desk_officer"),
        ("returned", "submitted", None),
        ("submitted", "originals_received", "records_officer"),
        ("originals_received", "verified", "etls_desk_officer"),
        ("originals_received", "rejected", "etls_desk_officer"),
        ("verified", "signed", "permanent_secretary"),
        ("signed", "sent_to_gra", "etls_desk_officer"),
        ("sent_to_gra", "closed", "etls_desk_officer"),
        # Cancelling a signed letter so a corrected one can be issued (0022).
        ("signed", "originals_received", "permanent_secretary"),
        ("sent_to_gra", "originals_received", "permanent_secretary"),
    }


async def test_the_applicant_starts_a_draft(act, people):
    response = await _submit(act, people["applicant"], product_approval_numbers=["PA-1", "PA-2"])
    assert response.status_code == 201, response.text
    body = response.json()
    # The applicant sees the plain label, never the internal step code.
    assert (body["status"], body["status_label"]) == (None, "Draft")
    assert body["reference"] is None  # given on submission
    assert body["quantity"] == "1200.500"  # NUMERIC(14, 3): exact, never 1200.4999...
    assert body["product_approval_numbers"] == ["PA-1", "PA-2"]
    [certificate] = body["certificates_of_origin"]
    assert certificate["number"] == "SN-CO-2026-0042"
    assert certificate["expires_on"] is not None  # six months after issued_on

    case = (await act(people["applicant"], "get", f"/cases/{body['case_id']}")).json()
    assert case["workflow"] == "etls_facility_letter"
    again = await act(people["desk"], "get", f"/etls/facility-letters/{body['case_id']}")
    assert again.json() == {**body, "status": "draft"}  # staff also get the code


async def test_the_applicant_edits_the_draft_and_the_changes_are_audited(act, people):
    case_id = (await _submit(act, people["applicant"])).json()["case_id"]
    changed = facility_letter_form(quantity="900", certificate_of_origin_numbers=["SN-CO-2026-0042", "SN-CO-2026-0043"])
    response = await act(people["applicant"], "put", f"/etls/facility-letters/{case_id}", json=changed)
    assert response.status_code == 200, response.text
    assert response.json()["quantity"] == "900.000"
    assert [c["number"] for c in response.json()["certificates_of_origin"]] == ["SN-CO-2026-0042", "SN-CO-2026-0043"]

    history = (await act(people["desk"], "get", f"/cases/{case_id}/history")).json()
    [edit] = [e for e in history if e["action"] == "case.form_updated"]
    assert edit["details"]["changes"] == {
        "quantity": {"from": "1200.5", "to": "900"},
        "certificates_of_origin": {
            "from": [changed["certificates_of_origin"][0]],
            "to": changed["certificates_of_origin"],
        },
    }
    # Saving the same form again changes nothing and adds no audit row.
    again = await act(people["applicant"], "put", f"/etls/facility-letters/{case_id}", json=changed)
    assert again.status_code == 200
    history = (await act(people["desk"], "get", f"/cases/{case_id}/history")).json()
    assert len([e for e in history if e["action"] == "case.form_updated"]) == 1


async def test_only_the_applicant_edits_and_only_while_a_draft(act, people, make_user):
    case_id = (await _submit(act, people["applicant"])).json()["case_id"]
    url = f"/etls/facility-letters/{case_id}"
    form = facility_letter_form(quantity="5")
    assert (await act(await make_user("applicant"), "put", url, json=form)).status_code == 404  # not theirs
    assert (await act(people["records_officer"], "put", url, json=form)).status_code == 403

    await upload_required(act, people["applicant"], case_id)
    assert (await submit(act, people["applicant"], case_id)).status_code == 200
    assert (await act(people["applicant"], "put", url, json=form)).status_code == 409
    case = (await act(people["applicant"], "get", f"/cases/{case_id}")).json()
    assert case["status"]["label"] == "Submitted"
    assert case["status"]["editable"] is False


async def test_only_the_applicant_may_submit(act, people):
    case_id = (await _submit(act, people["applicant"])).json()["case_id"]
    await upload_required(act, people["applicant"], case_id)
    for who in ("records_officer", "desk", "permanent_secretary"):
        assert (await submit(act, people[who], case_id)).status_code == 403, who
    # The applicant's move names no post: nobody acts for the applicant.
    response = await submit(act, people["applicant"], case_id)
    assert response.status_code == 200, response.text
    history = (await act(people["desk"], "get", f"/cases/{case_id}/history")).json()
    [submitted] = [e for e in history if e["action"] == "case.status_changed"]
    assert submitted["details"]["basis"] == "applicant"
    assert submitted["details"]["as_position"] is None
    assert submitted["acting_for"] is None


async def test_drafts_are_in_no_staff_queue(act, people):
    case_id = (await _submit(act, people["applicant"])).json()["case_id"]
    for who in ("records_officer", "desk"):
        queue = (await act(people[who], "get", "/cases/queue")).json()
        assert case_id not in [row["id"] for row in queue]


async def test_the_case_walks_the_whole_route(act, people):
    case_id = (await _submit(act, people["applicant"])).json()["case_id"]
    await ready_for_records(act, people, case_id)
    for who, to_status in ROUTE:
        if to_status == "verified":
            assert (await confirm_hs_code(act, people, case_id)).status_code == 200
        response = await move(act, people[who], case_id, to_status)
        assert response.status_code == 200, f"{who}: {response.text}"
    assert response.json()["status"]["is_final"] is True


@pytest.mark.parametrize(
    "changes",
    [
        {"product_approval_numbers": []},
        {"certificates_of_origin": []},
        {"certificates_of_origin": [certificate("CO 1"), certificate("co1")]},  # the same number twice
        {"certificates_of_origin": [{"number": "CO 1"}]},  # no issue date
        {"certificates_of_origin": [{"number": "CO 1", "issued_on": "2999-01-01"}]},
        {"product_approval_numbers": ["PA-1", "PA-1"]},
        {"quantity": "0"},
        {"quantity": "1.2345"},  # more than 3 decimal places
        {"importer_name": "   "},
        {"exporter_country": "x" * 201},
    ],
    ids=["no-approvals", "no-certificates", "repeated-certificate", "no-issue-date", "issued-in-future",
         "repeated-approval",
         "zero-quantity", "too-precise", "blank-name", "too-long"],
)
async def test_invalid_forms_are_refused(act, people, changes):
    assert (await _submit(act, people["applicant"], **changes)).status_code == 422


async def test_only_applicants_can_submit(act, people):
    assert (await _submit(act, people["desk"])).status_code == 403


async def test_the_generic_endpoint_cannot_open_a_facility_letter_case(act, people):
    # It would create a case with no form.
    response = await act(people["applicant"], "post", "/cases", json={"workflow": "etls_facility_letter"})
    assert response.status_code == 403


async def test_applicants_only_see_their_own_letters(act, people, make_user):
    case_id = (await _submit(act, people["applicant"])).json()["case_id"]
    other = await make_user("applicant")
    assert (await act(other, "get", f"/etls/facility-letters/{case_id}")).status_code == 404


async def test_a_case_of_another_workflow_is_not_a_facility_letter(act, people):
    case = await act(people["applicant"], "post", "/cases", json={"workflow": "etls_application"})
    response = await act(people["desk"], "get", f"/etls/facility-letters/{case.json()['id']}")
    assert response.status_code == 404
