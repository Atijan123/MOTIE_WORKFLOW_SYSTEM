from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, DateTime, ForeignKey, Identity, Index, Text, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

# Table created by alembic/versions/0003_audit_log.py. Postgres triggers there
# reject UPDATE, DELETE and TRUNCATE: rows can only ever be added.


class AuditEvent(Base):
    __tablename__ = "audit_log"
    __table_args__ = (
        Index("audit_log_entity_idx", "entity_type", "entity_id", "occurred_at"),
        {"schema": "core"},
    )
    __mapper_args__ = {"eager_defaults": True}

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    actor_user_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("core.users.id"))
    action: Mapped[str] = mapped_column(Text)
    entity_type: Mapped[str] = mapped_column(Text)
    entity_id: Mapped[str] = mapped_column(Text)
    details: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
