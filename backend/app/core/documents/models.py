"""Document tables. Created by alembic/versions/0017_documents.py."""

from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    SmallInteger,
    Text,
    UniqueConstraint,
    false,
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
    # The paper original must be seen in person, not just scanned (added in 0018).
    original_required: Mapped[bool] = mapped_column(Boolean, server_default=false())

    document_type: Mapped[DocumentType] = relationship(lazy="selectin", viewonly=True)


class CaseDocument(Base):
    """One uploaded file. The bytes are on disk under storage_key (see storage.py)."""

    __tablename__ = "case_documents"
    __table_args__ = (
        CheckConstraint("size_bytes > 0", name="case_documents_not_empty"),
        CheckConstraint(
            "(original_seen_at IS NULL) = (original_seen_by IS NULL)",
            name="case_documents_original_seen_complete",
        ),
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
    # Set when a staff member has seen the paper original of this upload (0018).
    original_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    original_seen_by: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("core.users.id"))

    document_type: Mapped[DocumentType] = relationship(lazy="selectin", viewonly=True)


class IssuedDocument(Base):
    """A document the Ministry issued on a case (e.g. a signed letter), stored once.

    Created by alembic/versions/0019_issued_documents.py. The app may only add
    rows, never change them, and there is at most one of each kind per case.
    """

    __tablename__ = "issued_documents"
    __table_args__ = (
        UniqueConstraint("case_id", "kind", name="issued_documents_once_per_case"),
        CheckConstraint("size_bytes > 0", name="issued_documents_not_empty"),
        {"schema": "core"},
    )
    __mapper_args__ = {"eager_defaults": True}

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    case_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("core.cases.id"))
    kind: Mapped[str] = mapped_column(Text)
    filename: Mapped[str] = mapped_column(Text)
    content_type: Mapped[str] = mapped_column(Text)
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    sha256: Mapped[str] = mapped_column(Text)
    storage_key: Mapped[str] = mapped_column(Text, unique=True)
    template_version: Mapped[str] = mapped_column(Text)
    template_sha256: Mapped[str] = mapped_column(Text)
    issued_by: Mapped[int] = mapped_column(BigInteger, ForeignKey("core.users.id"))
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
