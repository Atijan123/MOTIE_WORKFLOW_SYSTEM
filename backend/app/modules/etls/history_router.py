"""S13: ETLS statistics, the filtered table as CSV, and one historical letter's page."""

from datetime import date, datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, Query, Response
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.identity.deps import get_current_user
from app.core.identity.models import User
from app.core.workflow import service as workflow
from app.db.session import get_session
from app.modules.etls import statistics as stats

# Engine errors (WorkflowError) are turned into HTTP statuses by the handler in main.py.
router = APIRouter(prefix="/etls", tags=["etls statistics"])


class CountOut(BaseModel):
    label: str
    letters: int


class FigureOut(BaseModel):
    based_on: int  # how many letters the figure is based on
    rows: list[CountOut]
    note: str | None


class QuantityOut(BaseModel):
    category: str
    unit: str
    total: Decimal
    letters: int
    lines: int


class QuantityFigureOut(BaseModel):
    based_on: int
    rows: list[QuantityOut]
    lines_without_quantity: int


class SharedCertificateOut(BaseModel):
    number: str
    letters: list[str]


class SharedFigureOut(BaseModel):
    based_on: int  # letters with at least one certificate number
    rows: list[SharedCertificateOut]


class DataCheckOut(BaseModel):
    check_no_as_written: str | None
    folios: str | None
    reference: str | None
    what_looks_wrong: str | None
    what_to_check: str | None


class FiltersOut(BaseModel):
    date_from: date | None
    date_to: date | None
    importer: str | None


class StatisticsOut(BaseModel):
    letters: int
    live: int
    historical: int
    undated: int
    by_month: FigureOut
    by_year: FigureOut
    importers: FigureOut
    exporters: FigureOut
    exporter_countries: FigureOut
    products: FigureOut
    signatories: FigureOut
    quantities: QuantityFigureOut
    shared_certificates: SharedFigureOut
    unlinked_checks: list[DataCheckOut]
    filters: FiltersOut


def _filters(date_from: date | None, date_to: date | None, importer: str | None) -> stats.Filters:
    if date_from and date_to and date_from > date_to:
        raise workflow.InvalidDate("The date range ends before it starts.")
    return stats.Filters(date_from, date_to, (importer or "").strip() or None)


@router.get("/statistics", response_model=StatisticsOut)
async def statistics(
    date_from: date | None = None,
    date_to: date | None = None,
    importer: str | None = Query(default=None, max_length=200),
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """Live and historical facility letters together (repeat copies left out),
    filtered by date range and importer. The Director and stats_viewer only."""
    found = await stats.statistics(session, user, _filters(date_from, date_to, importer))
    return StatisticsOut.model_validate(found, from_attributes=True)


@router.get("/statistics/letters.csv", response_class=Response, responses={200: {"content": {"text/csv": {}}}})
async def statistics_csv(
    date_from: date | None = None,
    date_to: date | None = None,
    importer: str | None = Query(default=None, max_length=200),
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """The letters behind the figures, with the same filters, one row per letter."""
    filters = _filters(date_from, date_to, importer)
    found = await stats.letters(session, user, filters)
    span = "-".join(d.isoformat() for d in (filters.date_from, filters.date_to) if d) or "all"
    return Response(
        content=stats.to_csv(found),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="etls-facility-letters-{span}.csv"',
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )


class HistoricalGoodsOut(BaseModel):
    line_no_as_written: str | None
    product: str | None
    category: str | None
    quantity_as_written: str | None
    quantity: Decimal | None
    unit: str | None


class HistoricalLetterOut(BaseModel):
    """Every column of the register's row, as written."""

    id: int
    letter_no: int
    folios: str | None
    pdf_pages: str | None
    reference: str | None
    letter_date_as_written: str | None
    letter_date: date | None
    importer: str | None
    importer_address: str | None
    goods: str | None
    category: str | None
    exporter: str | None
    exporter_country: str | None
    exporter_approval_as_written: str | None
    exporter_approval_standard: str | None
    product_approvals: str | None
    tariff_codes: str | None
    certificates_as_written: str | None
    certificate_count_as_written: str | None
    bill_of_lading: str | None
    signed_by: str | None
    signed_as: str | None
    check_notes: str | None
    also_filed_at: str | None
    source_file: str | None
    source_page: int | None
    source_row: int
    imported_at: datetime


class HistoricalPageOut(BaseModel):
    letter: HistoricalLetterOut
    goods: list[HistoricalGoodsOut]
    certificates: list[str]
    checks: list[DataCheckOut]


@router.get("/history/{letter_id}", response_model=HistoricalPageOut)
async def historical_letter(
    letter_id: int,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """One historical letter: the register's row, its goods lines, certificates
    and data check notes. Read-only. Any staff member."""
    page = await stats.historical_letter(session, letter_id, user)
    return HistoricalPageOut(
        letter=HistoricalLetterOut.model_validate(page.letter, from_attributes=True),
        goods=[HistoricalGoodsOut.model_validate(g, from_attributes=True) for g in page.goods],
        certificates=[c.number for c in page.certificates],
        checks=[DataCheckOut.model_validate(c, from_attributes=True) for c in page.checks],
    )
