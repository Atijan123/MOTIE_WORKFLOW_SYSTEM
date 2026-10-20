"""The facility letter PDF: its fields, the signature block, the file reference
setting, and issuing it once at signing (stored, checksummed, never re-rendered)."""

import hashlib
from datetime import timedelta

import pytest
from pydantic import ValidationError
from sqlalchemy import select, text

from app.core.audit.models import AuditEvent
from app.core.config import Settings, settings
from app.core.documents import issued, storage
from app.core.documents.models import IssuedDocument
from app.core.workflow import effects
from app.core.workflow.delegation import today
from app.modules.etls import letter
from tests.support import confirm_hs_code, facility_letter_form, move, ready_for_records

pytestmark = pytest.mark.anyio


async def _verified_case(act, people, **form) -> int:
    response = await act(people["applicant"], "post", "/etls/facility-letters", json=facility_letter_form(**form))
    case_id = response.json()["case_id"]
    await ready_for_records(act, people, case_id)
    assert (await move(act, people["records_officer"], case_id, "originals_received")).status_code == 200
    assert (await confirm_hs_code(act, people, case_id)).status_code == 200
    response = await move(act, people["desk"], case_id, "verified")
    assert response.status_code == 200, response.text
    return case_id


async def _signed_case(act, people, signer="permanent_secretary", **form) -> int:
    case_id = await _verified_case(act, people, **form)
    response = await move(act, people[signer], case_id, "signed")
    assert response.status_code == 200, f"{signer}: {response.text}"
    return case_id


async def _events(db_session, case_id, action) -> list[AuditEvent]:
    return list(
        await db_session.scalars(
            select(AuditEvent)
            .where(AuditEvent.entity_id == str(case_id), AuditEvent.action == action)
            .order_by(AuditEvent.id)
        )
    )


async def _fields(db_session, case_id) -> letter.LetterFields:
    """The fields as they were at signing, built from the signing audit row."""
    moves = await _events(db_session, case_id, "case.status_changed")
    signing = [e for e in moves if e.details["to"] == "signed"][-1]
    return await letter.build_fields(db_session, case_id, signing)


def _stored_files(folder) -> set[str]:
    return {p.name for p in folder.iterdir()} if folder.exists() else set()


async def _status(db_session, case_id) -> str:
    return await db_session.scalar(
        text(
            "SELECT s.code FROM core.cases c JOIN core.workflow_statuses s ON s.id = c.current_status_id "
            "WHERE c.id = :id"
        ),
        {"id": case_id},
    )


# --- What is on the letter ---------------------------------------------------


async def test_the_letter_has_every_field(act, people, db_session):
    case_id = await _signed_case(
        act, people, product_approval_numbers=["PA-1", "PA-2"], certificate_of_origin_numbers=["CO-9", "CO-10"]
    )
    fields = await _fields(db_session, case_id)
    year = today().year

    assert fields.file_reference == f"MOTIE/ETLS/FL/{year}/{case_id:05d}"
    assert fields.date == f"{today().day} {today():%B %Y}"
    assert fields.importer_name == "Kombo Building Supplies Ltd"
    assert fields.importer_name_upper == "KOMBO BUILDING SUPPLIES LTD"
    assert fields.product == "Roofing sheets"
    assert fields.hs_code == "7210.49"  # the officer-confirmed code
    assert (fields.quantity, fields.unit) == ("1200.5", "tonnes")
    assert (fields.exporter_name, fields.exporter_country) == ("Dakar Steel SA", "Senegal")
    assert fields.exporter_approval_number == "SN-ETLS-0091"
    assert fields.product_approval_numbers == "PA-1, PA-2"
    assert fields.certificate_numbers == "CO-10, CO-9"
    # The PS signed in their own right.
    assert fields.signer_name == people["permanent_secretary"].full_name
    assert fields.signer_title == "Permanent Secretary"
    assert fields.acting_for == ""
    assert fields.signature_title == "Permanent Secretary"


async def test_the_pdf_shows_the_fields_on_the_page(act, people, db_session):
    fields = await _fields(db_session, await _signed_case(act, people))
    pdf = letter.render_pdf(fields, compress=False).decode("latin-1")

    assert pdf.startswith("%PDF-")
    # Long paragraphs wrap over several lines, so check phrases short enough to
    # stay on one line. (Inside a PDF string, "(" and ")" are written "\\(" and "\\)".)
    for expected in [
        fields.file_reference,
        fields.date,
        "The Commissioner General",
        "Gambia Revenue Authority",
        "REQUEST FOR ETLS FACILITY: KOMBO BUILDING SUPPLIES LTD",
        "clearance of goods \\(Roofing sheets\\)",
        "1200.5 tonnes of Roofing",
        "Dakar Steel SA of Senegal",
        "approval number SN-ETLS-0091",
        "SN-PA-2025-011",
        "SN-CO-2026-0042\\)",  # "Certificate of Origin (No. ...)": wraps before the number
        "Sincerely,",
        "Permanent Secretary",
        "Cc: Kombo Building Supplies Ltd",
        "12 Kairaba Avenue, Serrekunda",
    ]:
        assert expected in pdf, expected
    assert "version:" not in pdf  # the ## notes are never printed
    assert "For: " not in pdf  # the PS signed in their own right
    assert "$" not in pdf  # every placeholder was filled


async def test_the_reference_and_date_share_the_top_line(act, people, db_session):
    fields = await _fields(db_session, await _signed_case(act, people))
    pdf = letter.render_pdf(fields, compress=False).decode("latin-1")
    # fpdf2 writes each piece of text after its position: "<x> <y> Td (text) Tj".
    positions = {}
    for text in (fields.file_reference, fields.date):
        before = pdf[: pdf.index(f"({text}) Tj")].split()
        positions[text] = (float(before[-3]), float(before[-2]))
    (ref_x, ref_y), (date_x, date_y) = positions[fields.file_reference], positions[fields.date]
    assert ref_y == date_y  # same line
    assert date_x > ref_x + 200  # the date is over at the right margin


def test_layout_marks_come_from_the_template_not_the_data(tmp_path):
    template = tmp_path / "t.txt"
    template.write_text("## version: t\n$importer_name\n", encoding="utf-8")
    names = letter.LetterFields.__dataclass_fields__
    fields = letter.LetterFields(**{name: "x" for name in names})
    fields.importer_name = "**Bold >> Right**"
    pdf = letter.render_pdf(fields, letter.load_template(template), compress=False).decode("latin-1")
    assert "(**Bold >> Right**) Tj" in pdf  # printed as typed: not bold, not split


async def test_when_the_ps_is_away_the_signature_block_says_who_acted(act, people, db_session):
    start, end = today().isoformat(), (today() + timedelta(days=3)).isoformat()
    away = await act(people["permanent_secretary"], "post", "/absences", json={"starts_on": start, "ends_on": end})
    assert away.status_code == 201

    case_id = await _signed_case(act, people, signer="dps")
    fields = await _fields(db_session, case_id)

    assert fields.signer_name == people["dps"].full_name
    assert fields.signer_title == "Deputy Permanent Secretary, Administration and Finance"
    assert fields.acting_for == "for the Permanent Secretary"
    assert fields.signature_title == "For: Permanent Secretary"
    assert "For: Permanent Secretary" in letter.render_pdf(fields, compress=False).decode("latin-1")
    # ...and the stored letter records who issued it.
    assert (await issued.get_issued(db_session, case_id, letter.KIND)).issued_by == people["dps"].id


async def test_download_through_the_api(act, people):
    case_id = await _signed_case(act, people)
    response = await act(people["desk"], "get", f"/etls/facility-letters/{case_id}/letter.pdf")

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    assert response.content.startswith(b"%PDF-")
    assert response.headers["content-disposition"] == (
        f'attachment; filename="facility-letter-MOTIE-ETLS-FL-{today().year}-{case_id:05d}.pdf"'
    )
    assert response.headers["x-checksum-sha256"] == hashlib.sha256(response.content).hexdigest()


async def test_no_letter_before_it_is_signed(act, people, db_session):
    case_id = await _verified_case(act, people)
    assert (await act(people["desk"], "get", f"/etls/facility-letters/{case_id}/letter.pdf")).status_code == 409
    assert await issued.get_issued(db_session, case_id, letter.KIND) is None


async def test_applicants_cannot_download_it(act, people):
    case_id = await _signed_case(act, people)
    assert (await act(people["applicant"], "get", f"/etls/facility-letters/{case_id}/letter.pdf")).status_code == 403


async def test_the_file_reference_follows_the_setting(act, people, db_session, monkeypatch):
    monkeypatch.setattr(settings, "facility_letter_reference_format", "ETLS-{case_id}-{year}")
    case_id = await _signed_case(act, people)
    assert (await _fields(db_session, case_id)).file_reference == f"ETLS-{case_id}-{today().year}"


@pytest.mark.parametrize("bad", ["{case_id.__class__}", "{importer}", "{case_id[0]}"])
def test_the_reference_format_may_only_use_year_and_case_id(bad):
    # Checked when the app starts, not when the first letter is printed.
    with pytest.raises(ValidationError):
        Settings(facility_letter_reference_format=bad)


async def test_names_outside_latin1_do_not_break_the_pdf(act, people, db_session):
    fields = await _fields(db_session, await _signed_case(act, people))
    fields.importer_name = "Ŋaañ Trading 中"  # characters the built-in fonts lack
    assert letter.render_pdf(fields).startswith(b"%PDF-")


# --- Issued once, at signing -------------------------------------------------


async def test_signing_stores_the_letter_with_its_checksum_and_template_version(act, people, db_session):
    case_id = await _signed_case(act, people)

    document = await issued.get_issued(db_session, case_id, letter.KIND)
    content = storage.path_for(document.storage_key).read_bytes()
    assert content.startswith(b"%PDF-")
    assert document.sha256 == hashlib.sha256(content).hexdigest()
    assert document.size_bytes == len(content)
    assert document.issued_by == people["permanent_secretary"].id
    template = letter.load_template()
    assert (document.template_version, document.template_sha256) == (template.version, template.sha256)

    # The checksum and template version are in the audit log too, by the signer.
    [event] = await _events(db_session, case_id, "case.document_issued")
    assert event.actor_user_id == people["permanent_secretary"].id
    assert event.details["sha256"] == document.sha256
    assert event.details["template_version"] == template.version
    assert event.details["issued_document_id"] == document.id


async def test_downloads_serve_the_stored_file_and_never_render_again(act, people, monkeypatch):
    case_id = await _signed_case(act, people)

    def no_rendering(*args, **kwargs):
        raise AssertionError("a signed letter must not be rendered again")

    monkeypatch.setattr(letter, "render_pdf", no_rendering)
    url = f"/etls/facility-letters/{case_id}/letter.pdf"
    first = await act(people["desk"], "get", url)
    second = await act(people["records_officer"], "get", url)
    assert first.status_code == second.status_code == 200
    assert first.content == second.content


async def test_a_new_template_does_not_change_a_letter_already_issued(act, people, db_session, monkeypatch, tmp_path):
    case_id = await _signed_case(act, people)
    url = f"/etls/facility-letters/{case_id}/letter.pdf"
    before = (await act(people["desk"], "get", url)).content

    new_template = tmp_path / "new.txt"
    new_template.write_text("## version: 99\nCompletely new wording for $importer_name\n", encoding="utf-8")
    monkeypatch.setattr(letter, "TEMPLATE", new_template)

    assert (await act(people["desk"], "get", url)).content == before
    # A letter signed from now on uses the new template, and records which one.
    later = await _signed_case(act, people, certificate_of_origin_numbers=["CO-LATER"])
    assert (await issued.get_issued(db_session, later, letter.KIND)).template_version == "99"


async def test_if_issuing_fails_the_signing_fails_and_leaves_no_file(
    act, people, db_session, monkeypatch, document_storage
):
    case_id = await _verified_case(act, people)
    files_before = _stored_files(document_storage)

    def broken_audit(*args, **kwargs):  # fails after the PDF was written to disk
        raise RuntimeError("audit log unavailable")

    monkeypatch.setattr(issued, "record_event", broken_audit)
    with pytest.raises(RuntimeError):
        await move(act, people["permanent_secretary"], case_id, "signed")
    await db_session.rollback()  # what the real request's session does when it ends

    assert _stored_files(document_storage) == files_before
    assert await _status(db_session, case_id) == "verified"


async def test_a_letter_changed_on_disk_is_refused(act, people, db_session):
    case_id = await _signed_case(act, people)
    document = await issued.get_issued(db_session, case_id, letter.KIND)
    storage.path_for(document.storage_key).write_bytes(b"%PDF-1.7 something else")

    # Never served as the letter. (The test client re-raises; a real client gets 500.)
    with pytest.raises(storage.StoredFileChanged):
        await act(people["desk"], "get", f"/etls/facility-letters/{case_id}/letter.pdf")


async def test_a_case_gets_only_one_issued_letter(act, people, db_session):
    case_id = await _signed_case(act, people)
    for to_status in ["sent_to_gra", "closed"]:
        assert (await move(act, people["desk"], case_id, to_status)).status_code == 200
    rows = (await db_session.scalars(select(IssuedDocument).where(IssuedDocument.case_id == case_id))).all()
    assert len(rows) == 1


async def test_every_effect_named_in_the_database_has_code_behind_it(db_session):
    codes = set((await db_session.scalars(text("SELECT DISTINCT effect_code FROM core.transition_effects"))).all())
    assert codes and codes <= effects.registered()


async def test_an_effect_with_no_code_behind_it_blocks_the_move(act, people, db_session, monkeypatch):
    case_id = await _verified_case(act, people)
    monkeypatch.delitem(effects._effects, letter.ISSUE_EFFECT)

    response = await move(act, people["permanent_secretary"], case_id, "signed")
    assert response.status_code == 409
    assert letter.ISSUE_EFFECT in response.json()["detail"]
    await db_session.rollback()  # as the real request's session would
    assert await _status(db_session, case_id) == "verified"


def test_a_template_must_say_its_version(tmp_path):
    unlabelled = tmp_path / "letter.txt"
    unlabelled.write_text("Dear $importer_name\n", encoding="utf-8")
    with pytest.raises(ValueError, match="version"):
        letter.load_template(unlabelled)


def test_the_template_only_uses_fields_the_letter_has():
    # substitute() fails on an unknown $placeholder; fill every field with "x".
    names = letter.LetterFields.__dataclass_fields__
    fields = letter.LetterFields(**{name: "x" for name in names})
    assert letter.render_pdf(fields).startswith(b"%PDF-")
