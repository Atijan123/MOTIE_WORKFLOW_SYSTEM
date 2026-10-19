"""ETLS facility letter: the workflow definition, and submitting the form."""

import pytest
from sqlalchemy import text

from tests.support import facility_letter_form, move, ready_for_records

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
                "JOIN core.positions p ON p.id = x.required_position_id "
                "WHERE w.code = 'etls_facility_letter'"
            )
        )
    ).all()
    assert {tuple(r) for r in rows} == {
        ("submitted", "originals_received", "records_officer"),
        ("originals_received", "verified", "etls_desk_officer"),
        ("originals_received", "rejected", "etls_desk_officer"),
        ("verified", "signed", "permanent_secretary"),
        ("signed", "sent_to_gra", "etls_desk_officer"),
        ("sent_to_gra", "closed", "etls_desk_officer"),
    }


async def test_applicant_submits_the_form_and_a_case_opens(act, people):
    response = await _submit(act, people["applicant"], product_approval_numbers=["PA-1", "PA-2"])
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["status"] == "submitted"
    assert body["quantity"] == "1200.500"  # NUMERIC(14, 3): exact, never 1200.4999...
    assert body["product_approval_numbers"] == ["PA-1", "PA-2"]
    assert body["certificate_of_origin_numbers"] == ["SN-CO-2026-0042"]

    case = (await act(people["applicant"], "get", f"/cases/{body['case_id']}")).json()
    assert case["workflow"] == "etls_facility_letter"
    again = await act(people["desk"], "get", f"/etls/facility-letters/{body['case_id']}")
    assert again.json() == body


async def test_the_case_walks_the_whole_route(act, people):
    case_id = (await _submit(act, people["applicant"])).json()["case_id"]
    await ready_for_records(act, people, case_id)
    for who, to_status in ROUTE:
        response = await move(act, people[who], case_id, to_status)
        assert response.status_code == 200, f"{who}: {response.text}"
    assert response.json()["status"]["is_final"] is True


@pytest.mark.parametrize(
    "changes",
    [
        {"product_approval_numbers": []},
        {"certificate_of_origin_numbers": []},
        {"certificate_of_origin_numbers": ["CO 1", "co1"]},  # the same number twice
        {"product_approval_numbers": ["PA-1", "PA-1"]},
        {"quantity": "0"},
        {"quantity": "1.2345"},  # more than 3 decimal places
        {"importer_name": "   "},
        {"exporter_country": "x" * 201},
    ],
    ids=["no-approvals", "no-certificates", "repeated-certificate", "repeated-approval",
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
