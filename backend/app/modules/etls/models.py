"""ETLS module tables, in the "etls" schema. Created by alembic/versions/0015_etls_facility_letter.py.

They point at core.cases; core code never reads them.
"""

from decimal import Decimal

from sqlalchemy import BigInteger, CheckConstraint, ForeignKey, Index, Numeric, Text
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


class FacilityLetter(Base):
    """The importer's form for one etls_facility_letter case."""

    __tablename__ = "facility_letters"
    __table_args__ = (
        CheckConstraint("quantity > 0", name="facility_letters_quantity_positive"),
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

    product_approvals: Mapped[list[FacilityLetterProductApproval]] = relationship(
        lazy="selectin", order_by=FacilityLetterProductApproval.number
    )
    certificates: Mapped[list[FacilityLetterCertificate]] = relationship(
        lazy="selectin", order_by=FacilityLetterCertificate.number
    )
