"""Import the Ministry's register of historical facility letters (step 11).

    bash scripts/import-history.sh /path/to/ETLS_Facility_Letters_2025-2026.xlsx

which runs, with the file's folder mounted read-only at /data:

    docker compose run --rm -v <folder>:/data:ro tools \\
        python -m app.modules.etls.import_history /data/<file>

The register holds real importer data. It is read where it is, never copied
into the repository (the command refuses a file inside it), and tests use a
small made-up workbook written by write_register().

What it reads (sheet and column names must be exactly as below; other
sheets and extra columns are ignored):
- "Facility letters": one row per letter -> etls.historical_letters,
  and each "Certificate of origin no(s)." split on ";" -> historical_certificates;
- "Goods lines" -> historical_goods_lines, joined to their letter by "Letter no.";
- "Data checks" -> historical_data_checks, linked to the letters they mention.

Every cell is kept as written. Dates and quantities are also read into typed
columns when they can be; when they can't, the typed column is empty and the
text is still there. Re-running replaces the whole previous import, in one
transaction: a file with any problem changes nothing, and lists them all.
"""

import asyncio
import hashlib
import re
import sys
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

from openpyxl import Workbook, load_workbook
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit.service import record_event
from app.modules.etls.history_models import (
    HistoricalCertificate,
    HistoricalDataCheck,
    HistoricalDataCheckLetter,
    HistoricalGoodsLine,
    HistoricalLetter,
)
from app.modules.etls.schemas import normalize_certificate_number
from app.modules.etls.statistics import all_letters

LETTERS_SHEET = "Facility letters"
GOODS_SHEET = "Goods lines"
CHECKS_SHEET = "Data checks"

# Register heading -> column. The order is the register's.
LETTER_COLUMNS = {
    "Letter no.": "letter_no",
    "Folio(s) in file": "folios",
    "PDF page(s)": "pdf_pages",
    "Letter reference": "reference",
    "Letter date": "letter_date_as_written",
    "Importer": "importer",
    "Importer address / cc": "importer_address",
    "Goods (as in letter)": "goods",
    "Category": "category",
    "Exporter": "exporter",
    "Exporter country": "exporter_country",
    "Exporter approval no. (as written)": "exporter_approval_as_written",
    "Exporter approval no. (standard)": "exporter_approval_standard",
    "Product approval no(s).": "product_approvals",
    "Tariff code(s)": "tariff_codes",
    "Certificate of origin no(s).": "certificates_as_written",
    "No. of certificates": "certificate_count_as_written",
    "Bill of lading / container": "bill_of_lading",
    "Signed by": "signed_by",
    "Signed as": "signed_as",
    "Check notes": "check_notes",
    "Also filed at (second copy of this letter)": "also_filed_at",
}
GOODS_COLUMNS = {
    "Line no.": "line_no_as_written",
    "Letter no.": "letter_no_as_written",
    "Letter reference": "reference",
    "Letter date": "letter_date_as_written",
    "Importer": "importer",
    "Product": "product",
    "Category": "category",
    "Quantity": "quantity_as_written",
    "Unit": "unit",
    "Exporter": "exporter",
    "Exporter country": "exporter_country",
}
CHECK_COLUMNS = {
    "Check no.": "check_no_as_written",
    "Folio(s)": "folios",
    "Letter reference": "reference",
    "What looks wrong": "what_looks_wrong",
    "What to check": "what_to_check",
}
SHEETS = {LETTERS_SHEET: LETTER_COLUMNS, GOODS_SHEET: GOODS_COLUMNS, CHECKS_SHEET: CHECK_COLUMNS}

AUDIT_ENTITY = "etls_history"


class RegisterError(Exception):
    """The register can't be imported as it is. `problems` lists every one found."""

    def __init__(self, problems: list[str]):
        self.problems = problems
        super().__init__(f"{len(problems)} problem(s) in the register:\n" + "\n".join(f"- {p}" for p in problems))


# --- Reading cells -------------------------------------------------------------


def as_written(value) -> str | None:
    """A cell as text, the way it reads in the register. Empty -> None.

    Excel stores dates and numbers as such; they become "2025-10-16" and
    "12" (not "12.0"), so the text is still what a person typed."""
    if value is None:
        return None
    if isinstance(value, datetime):
        value = value.date() if value.time() == datetime.min.time() else value
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    text = str(value).strip()
    return text or None


_ORDINAL = re.compile(r"(\d+)(st|nd|rd|th)\b", re.IGNORECASE)
_DATE_FORMATS = ["%Y-%m-%d", "%d/%m/%Y", "%d.%m.%Y", "%d-%m-%Y", "%d %B %Y", "%d %b %Y", "%B %d %Y", "%d/%m/%y"]


def read_date(value) -> date | None:
    """A letter date, from an Excel date or text such as "16th October, 2025". None if unreadable."""
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = as_written(value)
    if not text:
        return None
    text = " ".join(_ORDINAL.sub(r"\1", text).replace(",", " ").split())
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def read_quantity(value) -> Decimal | None:
    """A quantity, from a number or text such as "1,200.5". None if unreadable."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return Decimal(str(value))
    text = (as_written(value) or "").replace(",", "").replace(" ", "")
    try:
        number = Decimal(text) if text else None
    except InvalidOperation:
        return None
    return number if number is not None and number.is_finite() else None


def read_int(value) -> int | None:
    text = as_written(value)
    return int(text) if text and text.isdigit() else None


def split_certificates(text: str | None) -> list[str]:
    """"SN-1; SN-2;" -> ["SN-1", "SN-2"]. The register separates numbers with ";"."""
    return [n.strip() for n in (text or "").replace("\n", ";").split(";") if n.strip()]


_FOLIO = re.compile(r"(\d+)\s*(?:[-–—]|to)\s*(\d+)|(\d+)")


def folio_set(text: str | None) -> set[int]:
    """"12-14, 17" -> {12, 13, 14, 17}. Used to find the letters a data check mentions."""
    found: set[int] = set()
    for start, end, single in _FOLIO.findall(text or ""):
        if single:
            found.add(int(single))
        elif int(end) >= int(start) and int(end) - int(start) < 500:  # a typo mustn't make a huge range
            found.update(range(int(start), int(end) + 1))
    return found


_SOURCE = re.compile(r"(File \d+),\s*p\.\s*(\d+)", re.IGNORECASE)


def read_source(text: str | None) -> tuple[str | None, int | None]:
    """"File 2, p. 7" -> ("File 2", 7): which scan a row came from. (None, None) if unreadable."""
    found = _SOURCE.fullmatch(text or "")
    return (found[1], int(found[2])) if found else (None, None)


def _same(text: str | None) -> str:
    """For comparing names and references written slightly differently."""
    return " ".join((text or "").split()).casefold()


# --- Reading the workbook --------------------------------------------------------


@dataclass
class Register:
    # One dict per row, keyed by our column names, with the raw cell values,
    # plus "_row" (the row number in the sheet).
    letters: list[dict] = field(default_factory=list)
    goods: list[dict] = field(default_factory=list)
    checks: list[dict] = field(default_factory=list)


def read_register(path: Path) -> Register:
    """The three sheets, row by row. Raises RegisterError if a sheet or column is missing."""
    try:
        workbook = load_workbook(path, read_only=True, data_only=True)
    except Exception as error:  # openpyxl raises several kinds for a file that isn't a workbook
        raise RegisterError([f"{path.name} can't be opened as an Excel workbook"]) from error
    problems, register = [], Register()
    try:
        for sheet_name, columns in SHEETS.items():
            if sheet_name not in workbook.sheetnames:
                problems.append(f'the sheet "{sheet_name}" is missing')
                continue
            rows = workbook[sheet_name].iter_rows(values_only=True)
            header = [as_written(h) for h in next(rows, ())]
            missing = [name for name in columns if name not in header]
            if missing:
                problems.append(f'sheet "{sheet_name}": missing column(s) ' + ", ".join(f'"{m}"' for m in missing))
                continue
            where = {columns[name]: header.index(name) for name in columns}
            target = {LETTERS_SHEET: register.letters, GOODS_SHEET: register.goods, CHECKS_SHEET: register.checks}[sheet_name]
            for number, row in enumerate(rows, start=2):
                values = {key: (row[i] if i < len(row) else None) for key, i in where.items()}
                if all(as_written(v) is None for v in values.values()):
                    continue  # blank rows between blocks
                target.append({**values, "_row": number})
    finally:
        workbook.close()
    if problems:
        raise RegisterError(problems)
    return register


# --- Turning rows into records ---------------------------------------------------


@dataclass
class Records:
    letters: list[HistoricalLetter]
    goods: list[tuple[int, HistoricalGoodsLine]]  # (letter no., line)
    certificates: list[tuple[int, HistoricalCertificate]]  # (letter no., certificate)
    checks: list[HistoricalDataCheck]


def build_records(register: Register) -> Records:
    """Check the rows and make the records. Raises RegisterError listing every
    problem, by sheet and row only: the messages reach a terminal, so they
    never quote a cell (CLAUDE.md, data rules)."""
    problems: list[str] = []
    letters: list[HistoricalLetter] = []
    certificates: list[tuple[int, HistoricalCertificate]] = []
    seen: dict[int, int] = {}  # letter no. -> its row

    for row in register.letters:
        where = f'"{LETTERS_SHEET}" row {row["_row"]}'
        letter_no = read_int(row["letter_no"])
        if letter_no is None:
            problems.append(f'{where}: "Letter no." must be a whole number')
            continue
        if letter_no in seen:
            problems.append(f'{where}: same "Letter no." as row {seen[letter_no]}')
            continue
        seen[letter_no] = row["_row"]
        text = {key: as_written(row[key]) for key in LETTER_COLUMNS.values() if key != "letter_no"}
        source_file, source_page = read_source(text["pdf_pages"])
        letters.append(
            HistoricalLetter(
                letter_no=letter_no,
                **text,
                letter_date=read_date(row["letter_date_as_written"]),
                source_file=source_file,
                source_page=source_page,
                source_row=row["_row"],
            )
        )
        for number in split_certificates(text["certificates_as_written"]):
            certificates.append(
                (letter_no, HistoricalCertificate(number=number, number_normalized=normalize_certificate_number(number)))
            )

    goods: list[tuple[int, HistoricalGoodsLine]] = []
    for row in register.goods:
        where = f'"{GOODS_SHEET}" row {row["_row"]}'
        letter_no = read_int(row["letter_no_as_written"])
        if letter_no not in seen:
            problems.append(f'{where}: "Letter no." isn\'t a letter in the register')
            continue
        goods.append(
            (
                letter_no,
                HistoricalGoodsLine(
                    **{key: as_written(row[key]) for key in GOODS_COLUMNS.values()},
                    quantity=read_quantity(row["quantity_as_written"]),
                    source_row=row["_row"],
                ),
            )
        )

    checks = [
        HistoricalDataCheck(**{key: as_written(row[key]) for key in CHECK_COLUMNS.values()}, source_row=row["_row"])
        for row in register.checks
    ]
    if problems:
        raise RegisterError(problems)
    return Records(letters, goods, certificates, checks)


def letters_mentioned(check: HistoricalDataCheck, letters: Iterable[HistoricalLetter]) -> list[HistoricalLetter]:
    """The letters a data check is about.

    By folio first: every letter whose "Folio(s) in file" shares a folio with
    the check's, narrowed to the check's reference when some match it. With
    no folios, by reference alone, but only if that reference points at one
    letter: a reference shared by many letters (such as the registry file
    reference) says nothing about which. [CONFIRM]
    """
    letters = list(letters)
    folios = folio_set(check.folios)
    reference = _same(check.reference)
    if folios:
        found = [l for l in letters if folio_set(l.folios) & folios]
        same_reference = [l for l in found if reference and _same(l.reference) == reference]
        return same_reference or found
    if not reference:
        return []
    found = [l for l in letters if _same(l.reference) == reference]
    return found if len(found) == 1 else []


# --- Storing -----------------------------------------------------------------------


@dataclass
class Summary:
    letters: int
    filed_twice: int
    unread_sources: int
    goods_lines: int
    certificates: int
    checks: int
    checks_unlinked: int
    undated_letters: int
    unread_quantities: int

    def lines(self) -> list[str]:
        return [
            f"{self.letters} letters ({self.filed_twice} with a second copy filed elsewhere; "
            f"{self.unread_sources} whose scan file and page couldn't be read)",
            f"{self.goods_lines} goods lines ({self.unread_quantities} with a quantity that couldn't be read as a number)",
            f"{self.certificates} certificate numbers",
            f"{self.checks} data checks ({self.checks_unlinked} not linked to any letter: see the Statistics page)",
            f"{self.undated_letters} letters whose date couldn't be read (kept as written; left out of monthly counts)",
        ]


HISTORY_TABLES = [HistoricalDataCheckLetter, HistoricalDataCheck, HistoricalCertificate, HistoricalGoodsLine, HistoricalLetter]


async def replace_history(session: AsyncSession, records: Records, *, source_file: str, sha256: str) -> Summary:
    """Replace the whole previous import with these records, and audit it, in
    one transaction. `session` must be the schema owner's: the API's database
    user may only read these tables."""
    for table in HISTORY_TABLES:  # children first
        await session.execute(delete(table))
    session.add_all(records.letters)
    await session.flush()  # gives each letter its id
    ids = {l.letter_no: l.id for l in records.letters}
    for letter_no, line in records.goods:
        line.letter_id = ids[letter_no]
    for letter_no, certificate in records.certificates:
        certificate.letter_id = ids[letter_no]
    session.add_all([line for _, line in records.goods] + [c for _, c in records.certificates] + records.checks)
    await session.flush()
    unlinked = 0
    for check in records.checks:
        mentioned = letters_mentioned(check, records.letters)
        unlinked += not mentioned
        session.add_all(HistoricalDataCheckLetter(check_id=check.id, letter_id=l.id) for l in mentioned)

    summary = Summary(
        letters=len(records.letters),
        filed_twice=sum(l.also_filed_at is not None for l in records.letters),
        unread_sources=sum(l.source_file is None for l in records.letters),
        goods_lines=len(records.goods),
        certificates=len(records.certificates),
        checks=len(records.checks),
        checks_unlinked=unlinked,
        undated_letters=sum(l.letter_date is None for l in records.letters),
        unread_quantities=sum(line.quantity is None for _, line in records.goods),
    )
    record_event(
        session,
        actor=None,  # run from the server's command line, not by a logged-in user
        action="etls.history_imported",
        entity_type=AUDIT_ENTITY,
        entity_id="register",
        # Which file, exactly (its checksum), and what came of it. No register content.
        details={"source_file": source_file, "sha256": sha256, **summary.__dict__},
    )
    await session.commit()
    return summary


async def import_file(session: AsyncSession, path: Path) -> Summary:
    content = path.read_bytes()
    records = build_records(read_register(path))
    return await replace_history(session, records, source_file=path.name, sha256=hashlib.sha256(content).hexdigest())


@dataclass
class PageTotals:
    """What the Statistics page shows with no filters, and the tables behind it."""

    letters: int
    live: int
    historical: int
    undated: int
    goods_lines: int
    certificates: int

    def lines(self) -> list[str]:
        return [
            f"{self.letters} letters: {self.live} signed in this system, {self.historical} from the historical register "
            f"({self.undated} with no readable date)",
            f"Behind them: {self.goods_lines} historical goods lines, {self.certificates} historical certificate numbers",
        ]


async def page_totals(session: AsyncSession) -> PageTotals:
    """`session` should be the API's own: then these are the rows the page can see."""
    found = await all_letters(session)
    return PageTotals(
        letters=len(found),
        live=sum(l.source == "live" for l in found),
        historical=sum(l.source == "historical" for l in found),
        undated=sum(l.date is None for l in found),
        goods_lines=await session.scalar(select(func.count()).select_from(HistoricalGoodsLine)),
        certificates=await session.scalar(select(func.count()).select_from(HistoricalCertificate)),
    )


# --- A made-up register, for tests and the demo ---------------------------------------


def write_register(path: Path, letters: list[dict], goods: list[dict] = (), checks: list[dict] = ()) -> Path:
    """Write a workbook with the register's sheets and headings. Each row is a
    dict keyed by register heading; missing headings are left empty."""
    workbook = Workbook()
    workbook.remove(workbook.active)
    for sheet_name, rows in ((LETTERS_SHEET, letters), (GOODS_SHEET, goods), (CHECKS_SHEET, checks)):
        sheet = workbook.create_sheet(sheet_name)
        headings = list(SHEETS[sheet_name])
        sheet.append(headings)
        for row in rows:
            sheet.append([row.get(h) for h in headings])
            # Text starting with "=" stays text. As a formula it would have no
            # saved result, and would read back empty.
            for cell in sheet[sheet.max_row]:
                if cell.data_type == "f":
                    cell.data_type = "s"
    workbook.save(path)
    return path


# --- The command --------------------------------------------------------------------

REPO = Path(__file__).resolve().parents[3]  # backend/ (mounted at /app in the containers)


async def _read_back() -> tuple[str, PageTotals | str]:
    """The database the app uses, and the totals it sees there (or why they couldn't be read)."""
    from sqlalchemy.engine import make_url
    from sqlalchemy.ext.asyncio import create_async_engine

    from app.core.config import settings

    url = make_url(settings.database_url)
    engine = create_async_engine(settings.database_url)
    try:
        async with AsyncSession(engine) as session:
            return f"{url.database} on {url.host}:{url.port}", await page_totals(session)
    except Exception as error:  # the import is already committed: don't report it as failed
        return f"{url.database} on {url.host}:{url.port}", type(error).__name__
    finally:
        await engine.dispose()


async def _main(path: Path) -> Summary:
    # Imported here so the checks in main() run before any connection is made.
    from sqlalchemy.ext.asyncio import create_async_engine

    from app.core.config import settings

    if not settings.migration_database_url:
        sys.exit("The import writes as the schema owner: run it from the tools container (MIGRATION_DATABASE_URL).")
    engine = create_async_engine(settings.migration_database_url)
    try:
        async with AsyncSession(engine, expire_on_commit=False) as session:
            return await import_file(session, path)
    finally:
        await engine.dispose()


def main(argv: list[str] | None = None) -> None:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1:
        sys.exit("Usage: python -m app.modules.etls.import_history /data/<register>.xlsx")
    path = Path(args[0]).resolve()
    if not path.is_file():
        sys.exit(f"No such file: {path}")
    if path.is_relative_to(REPO):
        # The register holds real importer data: keep it out of the repository.
        sys.exit(f"Refusing: {path} is inside the code folder. Keep the register outside the repository.")
    try:
        summary = asyncio.run(_main(path))
    except RegisterError as error:
        sys.exit(f"Nothing was imported. {error}")
    except Exception as error:
        # A database error's text and a traceback can both quote the row being
        # written, so only the kind of error is shown.
        sys.exit(f"Nothing was imported. The import stopped with an error of type {type(error).__name__}.")
    print(f"Imported {path.name}, replacing any earlier import:")
    for line in summary.lines():
        print(f"  {line}")
    # Read back as the API's own login, so what's printed is what the page can see.
    database, shown = asyncio.run(_read_back())
    print(f"The database the app uses: {database}")
    if isinstance(shown, str):
        print(f"The import is saved, but its totals couldn't be read back as the app ({shown}).")
        return
    print("The Statistics page will show, with no filters:")
    for line in shown.lines():
        print(f"  {line}")


if __name__ == "__main__":
    main()
