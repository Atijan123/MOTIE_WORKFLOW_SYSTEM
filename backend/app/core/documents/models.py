"""Document tables. Created by alembic/versions/0017_documents.py."""

from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    SmallInteger,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class DocumentType(Base):
    __tablename__ = "document_types"
    __table_args__ = {"schema": "core"}

    id: Mapped[int] = mapped_column(SmallInteger, Identity(), primary_key=True)
    code: Mapped[str] = mapped_column(Text, unique=True)
    name: Mapped[str] = mapped_column(Text)


class DocumentRequirement(Base):
    """A document a workflow needs, always or only when `condition` holds."""

    __tablename__ = "document_requirements"
    __table_args__ = (
        UniqueConstraint("workflow_id", "document_type_id", name="document_requirements_key"),
        CheckConstraint(
            "condition IS NULL OR ("
            "jsonb_typeof(condition) = 'object' "
            "AND condition ?& array['field', 'op', 'value'] "
            "AND condition->>'op' IN ('equals', 'contains'))",
            name="document_requirements_condition_shape",
        ),
        {"schema": "core"},
    )

    id: Mapped[int] = mapped_column(SmallInteger, Identity(), primary_key=True)
    workflow_id: Mapped[int] = mapped_column(SmallInteger, ForeignKey("core.workflows.id"))
    document_type_id: Mapped[int] = mapped_column(SmallInteger, ForeignKey("core.document_types.id"))
    condition: Mapped[dict[str, Any] | None] = mapped_column(JSONB)

    document_type: Mapped[DocumentType] = relationship(lazy="selectin", viewonly=True)


class CaseDocument(Base):
    """One uploaded file. The bytes are on disk under storage_key (see storage.py)."""

    __tablename__ = "case_documents"
    __table_args__ = (
        CheckConstraint("size_bytes > 0", name="case_documents_not_empty"),
        Index("case_documents_case_idx", "case_id"),
        {"schema": "core"},
    )
    __mapper_args__ = {"eager_defaults": True}

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    case_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("core.cases.id"))
    document_type_id: Mapped[int] = mapped_column(SmallInteger, ForeignKey("core.document_types.id"))
    filename: Mapped[str] = mapped_column(Text)
    content_type: Mapped[str] = mapped_column(Text)
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    sha256: Mapped[str] = mapped_column(Text)
    storage_key: Mapped[str] = mapped_column(Text, unique=True)
    uploaded_by: Mapped[int] = mapped_column(BigInteger, ForeignKey("core.users.id"))
    uploaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    document_type: Mapped[DocumentType] = relationship(lazy="selectin", viewonly=True)
