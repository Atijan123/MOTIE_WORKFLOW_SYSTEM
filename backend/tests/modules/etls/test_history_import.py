"""Importing the register of historical facility letters (step 11), with a
made-up workbook (tests/support.py made_up_register()). The real register is
never used in tests."""

from datetime import date, datetime
from decimal import Decimal

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError

from app.core.audit.models import AuditEvent
from app.modules.etls import import_history as importer
from app.modules.etls.history_models import (
    HistoricalCertificate,
    HistoricalDataCheck,
    HistoricalDataCheckLetter,
    HistoricalGoodsLine,
    HistoricalLetter,
)
from tests.support import HISTORICAL_CERTIFICATE, HISTORY_IMPORTER, made_up_register

pytestmark = pytest.mark.anyio


async def _letters(db_session) -> dict[int, HistoricalLetter]:
    return {l.letter_no: l for l in await db_session.scalars(select(HistoricalLetter))}


async def test_every_column_is_kept_as_written(import_history, db_session, tmp_path):
    summary = await import_history(made_up_register(tmp_path))
    assert (summary.letters, summary.filed_twice, summary.goods_lines, summary.checks) == (4, 1, 4, 3)

    letters = await _letters(db_session)
    first = letters[1]
    assert (first.folios, first.pdf_pages, first.reference) == ("3-4", "File 2, p. 7", "ADM/TEST/1")
    assert (first.letter_date_as_written, first.letter_date) == ("16th October, 2025", date(2025, 10, 16))
    assert (first.exporter_approval_as_written, first.exporter_approval_standard) == ("sn etls 1", "SN-ETLS-0001")
    assert first.certificate_count_as_written == "2"  # a number cell, as typed
    assert (first.signed_by, first.signed_as, first.check_notes) == ("A. Test Director", "For: Permanent Secretary", "Folio 4 is faint")
    assert (first.source_file, first.source_page, first.source_row) == ("File 2", 7, 2)
    # The second paper copy is a note on the letter, not another letter.
    assert first.also_filed_at == "File 5, p. 9 (folio 5)"
    assert letters[3].also_filed_at is None
    assert 2 not in letters
    # An Excel date cell, and a date nobody can read (kept as written).
    assert (letters[3].letter_date_as_written, letters[3].letter_date) == ("2026-01-20", date(2026, 1, 20))
    assert (letters[4].letter_date_as_written, letters[4].letter_date) == ("unclear", None)

    lines = {l.line_no_as_written: l for l in await db_session.scalars(select(HistoricalGoodsLine))}
    assert (lines["1"].quantity, lines["2"].quantity, lines["3"].quantity) == (Decimal(1200), Decimal("10.5"), Decimal(1000))
    assert (lines["4"].quantity_as_written, lines["4"].quantity) == ("about 300", None)
    assert lines["1"].letter_id == first.id

    numbers = [c.number for c in await db_session.scalars(
        select(HistoricalCertificate).where(HistoricalCertificate.letter_id == first.id).order_by(HistoricalCertificate.id)
    )]
    assert numbers == [HISTORICAL_CERTIFICATE, "HX-CO-2025-0002"]  # split on ";"


async def test_data_checks_are_linked_to_the_letters_they_mention(import_history, db_session, tmp_path):
    summary = await import_history(made_up_register(tmp_path))
    letters = await _letters(db_session)
    checks = {c.check_no_as_written: c for c in await db_session.scalars(select(HistoricalDataCheck))}
    links = {(l.check_id, l.letter_id) for l in await db_session.scalars(select(HistoricalDataCheckLetter))}
    assert (checks["1"].id, letters[1].id) in links  # folio 4 is on letter 1 (folios 3-4)
    assert (checks["2"].id, letters[3].id) in links  # by reference: one letter has it
    assert not any(c == checks["3"].id for c, _ in links)  # a reference no letter has: kept, unlinked
    assert summary.checks_unlinked == 1


async def test_running_it_again_replaces_the_earlier_import(import_history, db_session, tmp_path):
    await import_history(made_up_register(tmp_path))
    again = made_up_register(
        tmp_path,
        letters=[{"Letter no.": 7, "Letter reference": "ADM/TEST/7", "Importer": HISTORY_IMPORTER}],
        goods=[],
        checks=[],
    )
    await import_history(again)
    assert list(await _letters(db_session)) == [7]
    assert await db_session.scalar(select(HistoricalCertificate.id)) is None
    assert await db_session.scalar(select(HistoricalDataCheck.id)) is None


async def test_a_register_with_problems_changes_nothing(import_history, db_session, tmp_path):
    await import_history(made_up_register(tmp_path))
    bad = made_up_register(
        tmp_path,
        letters=[
            {"Letter no.": 1, "Importer": "One"},
            {"Letter no.": 1, "Importer": "Same number again"},
            {"Letter no.": "two", "Importer": "Not a number"},
        ],
        goods=[{"Line no.": 1, "Letter no.": 42, "Product": "Rice"}],
    )
    with pytest.raises(importer.RegisterError) as raised:
        await import_history(bad)
    problems = "\n".join(raised.value.problems)
    for expected in ("letter no. 1 is also on row 2", "must be a whole number", "'42' isn't a letter"):
        assert expected in problems, expected
    assert sorted(await _letters(db_session)) == [1, 3, 4, 5]  # the earlier import, untouched


async def test_a_missing_sheet_or_column_is_reported(tmp_path):
    from openpyxl import Workbook

    workbook = Workbook()
    workbook.active.title = "Facility letters"
    workbook.active.append(["Letter no.", "Importer"])
    path = tmp_path / "short.xlsx"
    workbook.save(path)
    with pytest.raises(importer.RegisterError) as raised:
        importer.read_register(path)
    problems = "\n".join(raised.value.problems)
    assert 'missing column(s) "Folio(s) in file"' in problems
    assert 'the sheet "Goods lines" is missing' in problems and 'the sheet "Data checks" is missing' in problems


async def test_the_import_is_audited_without_register_content(import_history, db_session, tmp_path):
    await import_history(made_up_register(tmp_path))
    event = await db_session.scalar(
        select(AuditEvent).where(AuditEvent.action == "etls.history_imported").order_by(AuditEvent.id.desc()).limit(1)
    )
    assert event.actor_user_id is None
    assert event.details["source_file"] == "made-up-register.xlsx" and len(event.details["sha256"]) == 64
    assert HISTORY_IMPORTER not in str(event.details)


async def test_the_api_user_can_only_read_history(db_session):
    for statement in (
        "INSERT INTO etls.historical_letters (letter_no, source_file, source_row) VALUES (999, 'x', 1)",
        "UPDATE etls.historical_letters SET importer = 'x'",
        "DELETE FROM etls.historical_certificates",
    ):
        with pytest.raises(DBAPIError, match="permission denied"):
            async with db_session.begin_nested():
                await db_session.execute(text(statement))


def test_the_command_refuses_a_register_inside_the_repository():
    with pytest.raises(SystemExit, match="Refusing"):
        importer.main([importer.__file__])  # any file inside the code folder


@pytest.mark.parametrize(
    "value, expected",
    [
        ("16th October, 2025", date(2025, 10, 16)),
        ("1st Nov 2025", date(2025, 11, 1)),
        ("03/11/2025", date(2025, 11, 3)),  # day first, as in The Gambia
        ("2025-11-03", date(2025, 11, 3)),
        (datetime(2025, 11, 3, 0, 0), date(2025, 11, 3)),
        ("unclear", None),
        (None, None),
    ],
)
def test_dates_are_read_when_they_can_be(value, expected):
    assert importer.read_date(value) == expected


def test_quantities_folios_and_certificates_are_read_carefully():
    assert importer.read_quantity("1,200.5") == Decimal("1200.5")
    assert importer.read_quantity(12.0) == Decimal("12.0")
    assert importer.read_quantity("about 300") is None
    assert importer.folio_set("12-14, 17") == {12, 13, 14, 17}
    assert importer.folio_set("3 to 4") == {3, 4}
    assert importer.folio_set("1-90000") == set()  # a typo mustn't link everything
    assert importer.split_certificates("A-1; A-2;\nA-3 ;") == ["A-1", "A-2", "A-3"]
    assert importer.read_source("File 12, p. 7") == ("File 12", 7)
    assert importer.read_source("page seven") == (None, None)
    assert importer.as_written(12.0) == "12" and importer.as_written("  x ") == "x" and importer.as_written("") is None
