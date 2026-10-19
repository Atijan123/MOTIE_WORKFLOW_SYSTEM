"""The facility letter PDF: its fields, the signature block, and the file reference setting."""

from datetime import timedelta

import pytest
from pydantic import ValidationError

from app.core.config import Settings, settings
from app.core.workflow.delegation import today
from app.modules.etls import letter
from tests.support import facility_letter_form, move, ready_for_records

pytestmark = pytest.mark.anyio


async def _signed_case(act, people, signer="permanent_secretary", **form) -> int:
    response = await act(people["applicant"], "post", "/etls/facility-letters", json=facility_letter_form(**form))
    case_id = response.json()["case_id"]
    await ready_for_records(act, people, case_id)
    for who, to_status in [("records_officer", "originals_received"), ("desk", "verified"), (signer, "signed")]:
        response = await move(act, people[who], case_id, to_status)
        assert response.status_code == 200, f"{who}: {response.text}"
    return case_id


async def _fields(db_session, people, case_id) -> letter.LetterFields:
    return await letter.letter_fields(db_session, case_id, people["desk"])


async def test_the_letter_has_every_field(act, people, db_session):
    case_id = await _signed_case(
        act, people, product_approval_numbers=["PA-1", "PA-2"], certificate_of_origin_numbers=["CO-9", "CO-10"]
    )
    fields = await _fields(db_session, people, case_id)
    year = today().year

    assert fields.file_reference == f"MOTIE/ETLS/FL/{year}/{case_id:05d}"
    assert fields.date == f"{today().day} {today():%B %Y}"
    assert fields.importer_name == "Kombo Building Supplies Ltd"
    assert fields.product == "Roofing sheets"
    assert fields.quantity == "1200.5 tonnes"
    assert (fields.exporter_name, fields.exporter_country) == ("Dakar Steel SA", "Senegal")
    assert fields.exporter_approval_number == "SN-ETLS-0091"
    assert fields.product_approval_numbers == "PA-1, PA-2"
    assert fields.certificate_numbers == "CO-10, CO-9"
    # The PS signed in their own right.
    assert fields.signer_name == people["permanent_secretary"].full_name
    assert fields.signer_title == "Permanent Secretary"
    assert fields.acting_for == ""


async def test_the_pdf_shows_the_fields_on_the_page(act, people, db_session):
    fields = await _fields(db_session, people, await _signed_case(act, people))
    pdf = letter.render_pdf(fields, compress=False).decode("latin-1")

    assert pdf.startswith("%PDF-")
    for expected in [
        f"Our ref: {fields.file_reference}",
        "The Commissioner General",
        "Gambia Revenue Authority",
        "Subject: Request for ETLS facility: Kombo Building Supplies Ltd",
        "Product: Roofing sheets",
        "Quantity: 1200.5 tonnes",
        "Exporter: Dakar Steel SA, Senegal",
        "Certificate",  # the certificate line ("(s)" is escaped inside a PDF string)
        "SN-CO-2026-0042",
        "SN-PA-2025-011",
        fields.signer_name,
        "cc: Kombo Building Supplies Ltd, 12 Kairaba Avenue, Serrekunda",
    ]:
        assert expected in pdf, expected


async def test_when_the_ps_is_away_the_signature_block_says_who_acted(act, people, db_session):
    start, end = today().isoformat(), (today() + timedelta(days=3)).isoformat()
    away = await act(people["permanent_secretary"], "post", "/absences", json={"starts_on": start, "ends_on": end})
    assert away.status_code == 201

    case_id = await _signed_case(act, people, signer="dps")
    fields = await _fields(db_session, people, case_id)

    assert fields.signer_name == people["dps"].full_name
    assert fields.signer_title == "Deputy Permanent Secretary, Administration and Finance"
    assert fields.acting_for == "for the Permanent Secretary"


async def test_download_through_the_api(act, people):
    case_id = await _signed_case(act, people)
    response = await act(people["desk"], "get", f"/etls/facility-letters/{case_id}/letter.pdf")

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    assert response.content.startswith(b"%PDF-")
    assert response.headers["content-disposition"] == (
        f'attachment; filename="facility-letter-MOTIE-ETLS-FL-{today().year}-{case_id:05d}.pdf"'
    )


async def test_no_letter_before_it_is_signed(act, people):
    response = await act(people["applicant"], "post", "/etls/facility-letters", json=facility_letter_form())
    case_id = response.json()["case_id"]
    assert (await act(people["desk"], "get", f"/etls/facility-letters/{case_id}/letter.pdf")).status_code == 409


async def test_applicants_cannot_download_it(act, people):
    case_id = await _signed_case(act, people)
    assert (await act(people["applicant"], "get", f"/etls/facility-letters/{case_id}/letter.pdf")).status_code == 403


async def test_the_file_reference_follows_the_setting(act, people, db_session, monkeypatch):
    monkeypatch.setattr(settings, "facility_letter_reference_format", "ETLS-{case_id}-{year}")
    case_id = await _signed_case(act, people)
    assert (await _fields(db_session, people, case_id)).file_reference == f"ETLS-{case_id}-{today().year}"


@pytest.mark.parametrize("bad", ["{case_id.__class__}", "{importer}", "{case_id[0]}"])
def test_the_reference_format_may_only_use_year_and_case_id(bad):
    # Checked when the app starts, not when the first letter is printed.
    with pytest.raises(ValidationError):
        Settings(facility_letter_reference_format=bad)


async def test_names_outside_latin1_do_not_break_the_pdf(act, people, db_session):
    fields = await _fields(db_session, people, await _signed_case(act, people))
    fields.importer_name = "Ŋaañ Trading 中"  # characters the built-in fonts lack
    assert letter.render_pdf(fields).startswith(b"%PDF-")
