"""ETLS module tables, in the "etls" schema. Created by alembic/versions/0015_etls_facility_letter.py.

They point at core.cases; core code never reads them.
"""

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import BigInteger, CheckConstraint, Date, DateTime, ForeignKey, Identity, Index, Numeric, Text, func
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
    # Valid for six months from this date (0028). Empty only on applications
    # from before then.
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
    importer_name: Mapped[str] = mapped_column(Text)
    importer_address: Mapped[str] = mapped_column(Text)
    product: Mapped[str] = mapped_column(Text)
    quantity: Mapped[Decimal] = mapped_column(Numeric(14, 3))
    unit: Mapped[str] = mapped_column(Text)
    exporter_name: Mapped[str] = mapped_column(Text)
    exporter_country: Mapped[str] = mapped_column(Text)
    exporter_etls_approval_number: Mapped[str] = mapped_column(Text)
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
