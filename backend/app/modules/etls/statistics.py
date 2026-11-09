"""ETLS statistics (SCREENS.md S13): live and historical facility letters together.

What counts as a letter:
- live: a facility letter case with a signed letter in force (a cancelled
  letter that was corrected counts once), dated the day the letter in force
  was signed;
- historical: a letter of the imported register, dated by its letter date.

Everything here is worked out from letters(), filtered the same way, so the
figures and the CSV always agree, and each figure says how many letters it
is based on. Names are grouped ignoring case and extra spaces ("KOMBO FEEDS
LTD" and "Kombo Feeds Ltd" are one importer), shown as first written.
Quantities are only ever added up within one category and one unit.
"""

import csv
import io
from collections import Counter
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.documents.models import IssuedDocument
from app.core.identity.models import User
from app.core.workflow import service as workflow
from app.core.workflow.models import Case
from app.modules.etls.history_models import (
    HistoricalCertificate,
    HistoricalDataCheck,
    HistoricalDataCheckLetter,
    HistoricalGoodsLine,
    HistoricalLetter,
)
from app.modules.etls.letter import KIND
from app.modules.etls.models import FacilityLetter, FacilityLetterCertificate
from app.modules.etls.schemas import normalize_certificate_number

VIEWER_ROLE = "stats_viewer"
# [CONFIRM] Who else may see the statistics (the PS? the Minister?).
DIRECTOR_POST = "director_of_industry"
NOT_RECORDED = "Not recorded"
TOP = 10


def may_view(user: User) -> bool:
    return VIEWER_ROLE in user.role_codes or DIRECTOR_POST in user.position_codes


def _require(user: User) -> None:
    if not may_view(user):
        raise workflow.NotPermitted("Only the Director and statistics viewers can see the ETLS statistics.")


def _key(text: str | None) -> str:
    return " ".join((text or "").split()).casefold()


@dataclass
class Goods:
    product: str | None
    category: str | None
    quantity: Decimal | None
    unit: str | None
    # False for a historical letter with no goods lines: its "Goods (as in
    # letter)" stands in for products, but it has no quantity to count or miss.
    is_line: bool = True


@dataclass
class Letter:
    source: str  # "live" or "historical"
    id: int  # case id, or historical letter id
    reference: str | None
    letter_no: int | None  # historical only
    date: date | None
    importer: str | None
    exporter: str | None
    exporter_country: str | None
    goods: list[Goods]
    certificates: list[str]  # as written
    signed_by: str | None
    signed_as: str | None


@dataclass
class Filters:
    date_from: date | None = None
    date_to: date | None = None
    importer: str | None = None  # part of the importer's name, any case

    def keeps(self, letter: Letter) -> bool:
        if (self.date_from or self.date_to) and letter.date is None:
            return False  # a letter with no readable date can't be in a date range
        if self.date_from and letter.date < self.date_from:
            return False
        if self.date_to and letter.date > self.date_to:
            return False
        return not self.importer or _key(self.importer) in _key(letter.importer)


async def _live(session: AsyncSession) -> list[Letter]:
    rows = (
        await session.execute(
            select(Case, FacilityLetter, IssuedDocument, User)
            .join(FacilityLetter, FacilityLetter.case_id == Case.id)
            .join(IssuedDocument, IssuedDocument.case_id == Case.id)
            .join(User, User.id == IssuedDocument.issued_by)
            .where(IssuedDocument.kind == KIND, IssuedDocument.cancelled_at.is_(None))
        )
    ).all()
    certificates: dict[int, list[str]] = {}
    for c in await session.scalars(
        select(FacilityLetterCertificate).where(FacilityLetterCertificate.case_id.in_([r[0].id for r in rows]))
    ):
        certificates.setdefault(c.case_id, []).append(c.number)
    return [
        Letter(
            source="live",
            id=case.id,
            reference=case.reference,
            letter_no=None,
            date=document.issued_at.date(),
            importer=form.importer_name,
            exporter=form.exporter_name,
            exporter_country=form.exporter_country,
            # [CONFIRM] Live applications have no "category" yet: shown as not recorded.
            goods=[Goods(form.product, None, form.quantity, form.unit)],
            certificates=sorted(certificates.get(case.id, [])),
            signed_by=signer.full_name,
            signed_as=document.signature_note,
        )
        for case, form, document, signer in rows
    ]


async def _historical(session: AsyncSession) -> list[Letter]:
    letters = list(await session.scalars(select(HistoricalLetter)))
    ids = [l.id for l in letters]
    goods: dict[int, list[Goods]] = {}
    for g in await session.scalars(
        select(HistoricalGoodsLine).where(HistoricalGoodsLine.letter_id.in_(ids)).order_by(HistoricalGoodsLine.id)
    ):
        goods.setdefault(g.letter_id, []).append(Goods(g.product, g.category, g.quantity, g.unit))
    certificates: dict[int, list[str]] = {}
    for c in await session.scalars(
        select(HistoricalCertificate).where(HistoricalCertificate.letter_id.in_(ids)).order_by(HistoricalCertificate.id)
    ):
        certificates.setdefault(c.letter_id, []).append(c.number)
    return [
        Letter(
            source="historical",
            id=l.id,
            reference=l.reference,
            letter_no=l.letter_no,
            date=l.letter_date,
            importer=l.importer,
            exporter=l.exporter,
            exporter_country=l.exporter_country,
            # A letter with no goods lines still has its goods as written.
            goods=goods.get(l.id) or [Goods(l.goods, l.category, None, None, is_line=False)],
            certificates=certificates.get(l.id, []),
            signed_by=l.signed_by,
            signed_as=l.signed_as,
        )
        for l in letters
    ]


async def letters(session: AsyncSession, user: User, filters: Filters) -> list[Letter]:
    """Every letter the filters keep, oldest first (undated last)."""
    _require(user)
    found = [l for l in await _live(session) + await _historical(session) if filters.keeps(l)]
    return sorted(found, key=lambda l: (l.date is None, l.date or date.min, l.source, l.id))


# --- Figures ----------------------------------------------------------------------


@dataclass
class Count:
    label: str
    letters: int


@dataclass
class Figure:
    """A table of counts, with how many letters it's based on."""

    based_on: int
    rows: list[Count]
    note: str | None = None


@dataclass
class Quantity:
    category: str
    unit: str
    total: Decimal
    letters: int
    lines: int


@dataclass
class QuantityFigure:
    based_on: int
    rows: list[Quantity]
    lines_without_quantity: int  # goods lines whose quantity or unit isn't recorded or readable


@dataclass
class SharedCertificate:
    number: str
    letters: list[str]  # "historical letter no. 12 (ADM/12, 2025-10-16)" or "FL/2026/0003 (2026-11-04)"


@dataclass
class SharedFigure:
    based_on: int
    rows: list[SharedCertificate]


@dataclass
class Statistics:
    letters: int  # all the letters the filters keep
    live: int
    historical: int
    undated: int
    by_month: Figure
    by_year: Figure
    importers: Figure
    exporters: Figure
    exporter_countries: Figure
    products: Figure
    signatories: Figure
    quantities: QuantityFigure
    shared_certificates: SharedFigure
    # Data checks the import couldn't tie to any letter, so they're not lost.
    unlinked_checks: list[HistoricalDataCheck] = field(default_factory=list)
    filters: Filters = field(default_factory=Filters)


def _counts(values_per_letter: list[list[str | None]], *, top: int | None = TOP) -> Figure:
    """One count per letter per distinct value (by _key). Letters with no value
    at all are counted under "Not recorded", so the rows add up."""
    counts: Counter[str] = Counter()
    shown: dict[str, str] = {}
    for values in values_per_letter:
        keys = {}
        for v in values:
            if _key(v):
                keys.setdefault(_key(v), " ".join(v.split()))
        if not keys:
            keys = {_key(NOT_RECORDED): NOT_RECORDED}
        for k, label in keys.items():
            shown.setdefault(k, label)
            counts[k] += 1
    rows = [Count(shown[k], n) for k, n in sorted(counts.items(), key=lambda kv: (-kv[1], shown[kv[0]].casefold()))]
    note = None
    if top is not None and len(rows) > top:
        note = f"Top {top} of {len(rows)}."
        rows = rows[:top]
    return Figure(len(values_per_letter), rows, note)


def _periods(found: list[Letter], fmt: str) -> Figure:
    dated = [l for l in found if l.date]
    counts = Counter(l.date.strftime(fmt) for l in dated)
    undated = len(found) - len(dated)
    return Figure(
        len(dated),
        [Count(period, counts[period]) for period in sorted(counts)],
        f"{undated} letter(s) with no readable date are not in this table." if undated else None,
    )


def _quantities(found: list[Letter]) -> QuantityFigure:
    totals: dict[tuple[str, str], list] = {}
    without = 0
    based_on = set()
    for l in found:
        for g in (g for g in l.goods if g.is_line):
            if g.quantity is None or not _key(g.unit):
                without += 1
                continue
            category = " ".join(g.category.split()) if _key(g.category) else NOT_RECORDED
            # Never add different units: "tonnes" and "bags" are separate rows, always.
            key = (_key(category), _key(g.unit))
            entry = totals.setdefault(key, [category, " ".join(g.unit.split()), Decimal(0), set(), 0])
            entry[2] += g.quantity
            entry[3].add((l.source, l.id))
            entry[4] += 1
            based_on.add((l.source, l.id))
    rows = [
        Quantity(category, unit, total, len(letters_), lines)
        for category, unit, total, letters_, lines in sorted(totals.values(), key=lambda e: (e[0].casefold(), e[1].casefold()))
    ]
    return QuantityFigure(len(based_on), rows, without)


def _describe(l: Letter) -> str:
    when = l.date.isoformat() if l.date else "no date"
    if l.source == "live":
        return f"{(l.reference or '').replace('MOTIE/ETLS/', '')} ({when})"
    return f"historical letter no. {l.letter_no} ({l.reference or 'no reference'}, {when})"


def _shared(found: list[Letter]) -> SharedFigure:
    """Certificate numbers on more than one letter, compared the way the
    duplicate check compares them."""
    uses: dict[str, list[Letter]] = {}
    shown: dict[str, str] = {}
    for l in found:
        for normalized, typed in {normalize_certificate_number(n): n for n in l.certificates}.items():
            uses.setdefault(normalized, []).append(l)
            shown.setdefault(normalized, typed)
    rows = [SharedCertificate(shown[n], [_describe(l) for l in ls]) for n, ls in sorted(uses.items()) if len(ls) > 1]
    return SharedFigure(sum(bool(l.certificates) for l in found), rows)


async def statistics(session: AsyncSession, user: User, filters: Filters) -> Statistics:
    found = await letters(session, user, filters)
    unlinked = list(
        await session.scalars(
            select(HistoricalDataCheck)
            .where(~HistoricalDataCheck.id.in_(select(HistoricalDataCheckLetter.check_id)))
            .order_by(HistoricalDataCheck.source_row)
        )
    )
    return Statistics(
        letters=len(found),
        live=sum(l.source == "live" for l in found),
        historical=sum(l.source == "historical" for l in found),
        undated=sum(l.date is None for l in found),
        by_month=_periods(found, "%Y-%m"),
        by_year=_periods(found, "%Y"),
        importers=_counts([[l.importer] for l in found]),
        exporters=_counts([[l.exporter] for l in found]),
        exporter_countries=_counts([[l.exporter_country] for l in found]),
        products=_counts([[g.product for g in l.goods] for l in found]),
        signatories=_counts([[l.signed_by] for l in found], top=None),
        quantities=_quantities(found),
        shared_certificates=_shared(found),
        unlinked_checks=unlinked,
        filters=filters,
    )


# --- The filtered table as CSV ------------------------------------------------------

CSV_HEADINGS = [
    "Source", "Reference", "Letter no.", "Date", "Importer", "Exporter", "Exporter country",
    "Products", "Quantities", "Certificates of origin", "Signed by", "Signed as",
]


def _cell(value) -> str:
    """Text for a spreadsheet cell. A leading = + - @ (or tab/CR) would make
    Excel run it as a formula, so such a cell is prefixed with ' (CSV injection)."""
    text = "" if value is None else str(value)
    return "'" + text if text[:1] in ("=", "+", "-", "@", "\t", "\r") else text


def to_csv(found: list[Letter]) -> str:
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(CSV_HEADINGS)
    for l in found:
        writer.writerow(
            _cell(v)
            for v in [
                l.source,
                l.reference,
                l.letter_no,
                l.date.isoformat() if l.date else "",
                l.importer,
                l.exporter,
                l.exporter_country,
                "; ".join(g.product for g in l.goods if g.product),
                "; ".join(f"{format(g.quantity.normalize(), 'f')} {g.unit or ''}".strip() for g in l.goods if g.quantity is not None),
                "; ".join(l.certificates),
                l.signed_by,
                l.signed_as,
            ]
        )
    # A byte-order mark so Excel opens names such as "Côte d’Ivoire" correctly.
    return "﻿" + out.getvalue()


# --- One historical letter ---------------------------------------------------------


@dataclass
class HistoricalPage:
    letter: HistoricalLetter
    goods: list[HistoricalGoodsLine]
    certificates: list[HistoricalCertificate]
    checks: list[HistoricalDataCheck]


async def historical_letter(session: AsyncSession, letter_id: int, user: User) -> HistoricalPage:
    """One historical letter with everything the register says about it. Any
    staff member may open one (the desk follows a duplicate flag to it)."""
    if not workflow.is_staff(user):
        raise workflow.NotPermitted("Only Ministry staff can see historical letters.")
    letter = await session.get(HistoricalLetter, letter_id)
    if letter is None:
        raise workflow.NotFound("Historical letter not found.")

    async def by(model, *where, order):
        return list(await session.scalars(select(model).where(*where).order_by(order)))

    return HistoricalPage(
        letter=letter,
        goods=await by(HistoricalGoodsLine, HistoricalGoodsLine.letter_id == letter.id, order=HistoricalGoodsLine.id),
        certificates=await by(HistoricalCertificate, HistoricalCertificate.letter_id == letter.id, order=HistoricalCertificate.id),
        checks=await by(
            HistoricalDataCheck,
            HistoricalDataCheck.id.in_(
                select(HistoricalDataCheckLetter.check_id).where(HistoricalDataCheckLetter.letter_id == letter.id)
            ),
            order=HistoricalDataCheck.id,
        ),
    )
