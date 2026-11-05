"""ETLS module tables, in the "etls" schema. Created by alembic/versions/0015_etls_facility_letter.py.

They point at core.cases; core code never reads them.
"""

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Numeric,
    SmallInteger,
    Text,
    UniqueConstraint,
    func,
    text,
    true,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class FacilityLetterProductApproval(Base):
    __tablename__ = "facility_letter_product_approvals"
    __table_args__ = {"schema": "etls"}

    case_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("etls.facility_letters.case_id"), primary_key=True
    )
    number: Mapped[str] = mapped_column(Text, primary_key=True)


class FacilityLetterCertificate(Base):
    """A certificate of origin number on a facility letter request."""

    __tablename__ = "facility_letter_certificates"
    __table_args__ = (
        Index("facility_letter_certificates_number_idx", "number_normalized"),
        {"schema": "etls"},
    )

    case_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("etls.facility_letters.case_id"), primary_key=True
    )
    number: Mapped[str] = mapped_column(Text)  # as typed, for the letter
    number_normalized: Mapped[str] = mapped_column(Text, primary_key=True)  # for comparing
    # Valid for six months from this date (0028). Empty on a draft not yet
    # finished (0034), and on applications from before 0028.
    issued_on: Mapped[date | None] = mapped_column(Date)


class FacilityLetterDispatch(Base):
    """A signed letter sent to GRA: which issued letter, and on which day (0030)."""

    __tablename__ = "facility_letter_dispatches"
    __table_args__ = (
        Index("facility_letter_dispatches_case_idx", "case_id"),
        {"schema": "etls"},
    )
    __mapper_args__ = {"eager_defaults": True}

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    case_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("etls.facility_letters.case_id"))
    issued_document_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("core.issued_documents.id"), unique=True)
    dispatched_on: Mapped[date] = mapped_column(Date)
    recorded_by: Mapped[int] = mapped_column(BigInteger, ForeignKey("core.users.id"))
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class FacilityLetterCopy(Base):
    """One of the three copies of a signed letter (0041): Records' file copy,
    GRA's, and the applicant's. Written once, when the letter is issued."""

    __tablename__ = "facility_letter_copies"
    __table_args__ = (
        CheckConstraint("recipient IN ('records_file', 'gra', 'applicant')", name="facility_letter_copies_recipient"),
        UniqueConstraint("issued_document_id", "recipient", name="facility_letter_copies_one_each"),
        Index("facility_letter_copies_case_idx", "case_id"),
        {"schema": "etls"},
    )
    __mapper_args__ = {"eager_defaults": True}

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    case_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("etls.facility_letters.case_id"))
    issued_document_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("core.issued_documents.id"))
    recipient: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class FacilityLetter(Base):
    """The importer's form for one etls_facility_letter case."""

    __tablename__ = "facility_letters"
    __table_args__ = (
        CheckConstraint("quantity > 0", name="facility_letters_quantity_positive"),
        # Added in 0020; see the migration for the HS code shape.
        CheckConstraint(r"hs_code ~ '^[0-9]{6}([0-9]{2}){0,2}$'", name="facility_letters_hs_code_shape"),
        CheckConstraint(
            r"hs_code_confirmed ~ '^[0-9]{6}([0-9]{2}){0,2}$'", name="facility_letters_hs_code_confirmed_shape"
        ),
        CheckConstraint(
            "(hs_code_confirmed IS NULL) = (hs_code_confirmed_by IS NULL) "
            "AND (hs_code_confirmed IS NULL) = (hs_code_confirmed_at IS NULL)",
            name="facility_letters_hs_code_confirmed_complete",
        ),
        {"schema": "etls"},
    )

    case_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("core.cases.id"), primary_key=True)
    # Empty only while a draft (0034): the check etls_form_complete on Submit
    # makes sure a submitted application has them all.
    importer_name: Mapped[str | None] = mapped_column(Text)
    importer_address: Mapped[str | None] = mapped_column(Text)
    product: Mapped[str | None] = mapped_column(Text)
    quantity: Mapped[Decimal | None] = mapped_column(Numeric(14, 3))
    unit: Mapped[str | None] = mapped_column(Text)
    exporter_name: Mapped[str | None] = mapped_column(Text)
    exporter_country: Mapped[str | None] = mapped_column(Text)
    exporter_etls_approval_number: Mapped[str | None] = mapped_column(Text)
    # The HS code as the applicant declared it, and as an officer confirmed it
    # (digits only). Empty on cases submitted before 0020.
    hs_code: Mapped[str | None] = mapped_column(Text)
    hs_code_confirmed: Mapped[str | None] = mapped_column(Text)
    hs_code_confirmed_by: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("core.users.id"))
    hs_code_confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    product_approvals: Mapped[list[FacilityLetterProductApproval]] = relationship(
        lazy="selectin", order_by=FacilityLetterProductApproval.number
    )
    certificates: Mapped[list[FacilityLetterCertificate]] = relationship(
        lazy="selectin", order_by=FacilityLetterCertificate.number
    )


class _ChoiceList:
    """An entry in a list the form picks from, kept by an admin (0039).

    Change only through modules/etls/choices.py, which writes the audit rows.
    Never deleted: switched off (active = false) instead.
    """

    id: Mapped[int] = mapped_column(SmallInteger, Identity(), primary_key=True)
    name: Mapped[str] = mapped_column(Text)
    active: Mapped[bool] = mapped_column(Boolean, server_default=true())
    sort_order: Mapped[int] = mapped_column(SmallInteger)


class Country(_ChoiceList, Base):
    """An exporter's country the form offers."""

    __tablename__ = "countries"
    __table_args__ = (
        # "Ghana" and "ghana" are the same entry (0039).
        Index("countries_name_key", text("lower(name)"), unique=True),
        CheckConstraint("btrim(name) <> '' AND name = btrim(name)", name="countries_name_trimmed"),
        {"schema": "etls"},
    )


class Unit(_ChoiceList, Base):
    """A unit for the quantity ("bags", "tonnes")."""

    __tablename__ = "units"
    __table_args__ = (
        # "Ghana" and "ghana" are the same entry (0039).
        Index("units_name_key", text("lower(name)"), unique=True),
        CheckConstraint("btrim(name) <> '' AND name = btrim(name)", name="units_name_trimmed"),
        {"schema": "etls"},
    )
