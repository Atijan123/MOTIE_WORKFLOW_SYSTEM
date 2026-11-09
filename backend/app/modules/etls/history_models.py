"""Historical facility letters from the Excel register (alembic/versions/0042_historical_facility_letters.py).

Read-only for the API. Only the import (app/modules/etls/import_history.py,
run as the schema owner) writes them, and it replaces them all at once.
"""

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Date,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Integer,
    Numeric,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class HistoricalLetter(Base):
    """One letter: a row of the register's "Facility letters" sheet, as written."""

    __tablename__ = "historical_letters"
    __table_args__ = (
        Index("historical_letters_date_idx", "letter_date"),
        {"schema": "etls"},
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    letter_no: Mapped[int] = mapped_column(Integer, unique=True)
    folios: Mapped[str | None] = mapped_column(Text)
    pdf_pages: Mapped[str | None] = mapped_column(Text)
    reference: Mapped[str | None] = mapped_column(Text)
    letter_date_as_written: Mapped[str | None] = mapped_column(Text)
    importer: Mapped[str | None] = mapped_column(Text)
    importer_address: Mapped[str | None] = mapped_column(Text)
    goods: Mapped[str | None] = mapped_column(Text)
    category: Mapped[str | None] = mapped_column(Text)
    exporter: Mapped[str | None] = mapped_column(Text)
    exporter_country: Mapped[str | None] = mapped_column(Text)
    exporter_approval_as_written: Mapped[str | None] = mapped_column(Text)
    exporter_approval_standard: Mapped[str | None] = mapped_column(Text)
    product_approvals: Mapped[str | None] = mapped_column(Text)
    tariff_codes: Mapped[str | None] = mapped_column(Text)
    certificates_as_written: Mapped[str | None] = mapped_column(Text)
    certificate_count_as_written: Mapped[str | None] = mapped_column(Text)
    bill_of_lading: Mapped[str | None] = mapped_column(Text)
    signed_by: Mapped[str | None] = mapped_column(Text)
    signed_as: Mapped[str | None] = mapped_column(Text)
    check_notes: Mapped[str | None] = mapped_column(Text)
    also_filed_at: Mapped[str | None] = mapped_column(Text)
    letter_date: Mapped[date | None] = mapped_column(Date)
    source_file: Mapped[str | None] = mapped_column(Text)
    source_page: Mapped[int | None] = mapped_column(Integer)
    source_row: Mapped[int] = mapped_column(Integer)
    imported_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class HistoricalGoodsLine(Base):
    """One row of the "Goods lines" sheet, as written, with the quantity read as a number."""

    __tablename__ = "historical_goods_lines"
    __table_args__ = (Index("historical_goods_lines_letter_idx", "letter_id"), {"schema": "etls"})

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    letter_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("etls.historical_letters.id"))
    line_no_as_written: Mapped[str | None] = mapped_column(Text)
    letter_no_as_written: Mapped[str | None] = mapped_column(Text)
    reference: Mapped[str | None] = mapped_column(Text)
    letter_date_as_written: Mapped[str | None] = mapped_column(Text)
    importer: Mapped[str | None] = mapped_column(Text)
    product: Mapped[str | None] = mapped_column(Text)
    category: Mapped[str | None] = mapped_column(Text)
    quantity_as_written: Mapped[str | None] = mapped_column(Text)
    unit: Mapped[str | None] = mapped_column(Text)
    exporter: Mapped[str | None] = mapped_column(Text)
    exporter_country: Mapped[str | None] = mapped_column(Text)
    quantity: Mapped[Decimal | None] = mapped_column(Numeric(18, 3))
    source_row: Mapped[int] = mapped_column(Integer)


class HistoricalCertificate(Base):
    """One certificate of origin number from a historical letter."""

    __tablename__ = "historical_certificates"
    __table_args__ = (
        Index("historical_certificates_number_idx", "number_normalized"),
        Index("historical_certificates_letter_idx", "letter_id"),
        {"schema": "etls"},
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    letter_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("etls.historical_letters.id"))
    number: Mapped[str] = mapped_column(Text)
    number_normalized: Mapped[str] = mapped_column(Text)


class HistoricalDataCheck(Base):
    """One row of the "Data checks" sheet: a note about letters that look wrong."""

    __tablename__ = "historical_data_checks"
    __table_args__ = {"schema": "etls"}

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    check_no_as_written: Mapped[str | None] = mapped_column(Text)
    folios: Mapped[str | None] = mapped_column(Text)
    reference: Mapped[str | None] = mapped_column(Text)
    what_looks_wrong: Mapped[str | None] = mapped_column(Text)
    what_to_check: Mapped[str | None] = mapped_column(Text)
    source_row: Mapped[int] = mapped_column(Integer)


class HistoricalDataCheckLetter(Base):
    """A data check note linked to a letter it mentions."""

    __tablename__ = "historical_data_check_letters"
    __table_args__ = {"schema": "etls"}

    check_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("etls.historical_data_checks.id"), primary_key=True)
    letter_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("etls.historical_letters.id"), primary_key=True)
