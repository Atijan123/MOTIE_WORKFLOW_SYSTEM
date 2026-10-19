from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Identity,
    Index,
    Integer,
    SmallInteger,
    Text,
    UniqueConstraint,
    false,
    func,
    text,
    true,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.identity.models import Position, Role
from app.db.base import Base

# Tables created by alembic/versions/0004_workflow_definitions.py (since 0009,
# transitions name a position instead of a role).
# The relationships are viewonly: workflow definitions are written by migrations,
# never through these classes, so SQLAlchemy only needs to *read* them.


class Workflow(Base):
    __tablename__ = "workflows"
    __table_args__ = {"schema": "core"}

    id: Mapped[int] = mapped_column(SmallInteger, Identity(), primary_key=True)
    code: Mapped[str] = mapped_column(Text, unique=True)
    name: Mapped[str] = mapped_column(Text)
    start_role_id: Mapped[int] = mapped_column(SmallInteger, ForeignKey("core.roles.id"))
    # Set (e.g. "etls") when the module's own endpoint opens these cases, because
    # each case needs the module's form saved with it. Added in 0015.
    opened_by_module: Mapped[str | None] = mapped_column(Text)

    start_role: Mapped[Role] = relationship(lazy="selectin", viewonly=True)


class WorkflowStatus(Base):
    __tablename__ = "workflow_statuses"
    __table_args__ = (
        UniqueConstraint("workflow_id", "code", name="workflow_statuses_workflow_code_key"),
        UniqueConstraint("workflow_id", "id", name="workflow_statuses_workflow_id_id_key"),
        CheckConstraint("NOT (is_initial AND is_final)", name="workflow_statuses_not_both"),
        Index(
            "workflow_statuses_one_initial",
            "workflow_id",
            unique=True,
            postgresql_where=text("is_initial"),
        ),
        {"schema": "core"},
    )

    id: Mapped[int] = mapped_column(Integer, Identity(), primary_key=True)
    workflow_id: Mapped[int] = mapped_column(SmallInteger, ForeignKey("core.workflows.id"))
    code: Mapped[str] = mapped_column(Text)
    name: Mapped[str] = mapped_column(Text)
    is_initial: Mapped[bool] = mapped_column(Boolean, server_default=false())
    is_final: Mapped[bool] = mapped_column(Boolean, server_default=false())


class WorkflowTransition(Base):
    __tablename__ = "workflow_transitions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["workflow_id", "from_status_id"],
            ["core.workflow_statuses.workflow_id", "core.workflow_statuses.id"],
            name="workflow_transitions_from_fkey",
        ),
        ForeignKeyConstraint(
            ["workflow_id", "to_status_id"],
            ["core.workflow_statuses.workflow_id", "core.workflow_statuses.id"],
            name="workflow_transitions_to_fkey",
        ),
        UniqueConstraint(
            "from_status_id",
            "to_status_id",
            "required_position_id",
            name="workflow_transitions_move_key",
        ),
        CheckConstraint("from_status_id <> to_status_id", name="workflow_transitions_no_self_loop"),
        {"schema": "core"},
    )

    id: Mapped[int] = mapped_column(Integer, Identity(), primary_key=True)
    workflow_id: Mapped[int] = mapped_column(SmallInteger)
    from_status_id: Mapped[int] = mapped_column(Integer)
    to_status_id: Mapped[int] = mapped_column(Integer)
    # The post whose holders may make this move (or anyone acting for that post).
    required_position_id: Mapped[int] = mapped_column(SmallInteger, ForeignKey("core.positions.id"))
    name: Mapped[str] = mapped_column(Text)

    # Two links to the same table (from and to), so each says which column it uses.
    from_status: Mapped[WorkflowStatus] = relationship(
        primaryjoin="WorkflowStatus.id == WorkflowTransition.from_status_id",
        foreign_keys=[from_status_id],
        lazy="selectin",
        viewonly=True,
    )
    to_status: Mapped[WorkflowStatus] = relationship(
        primaryjoin="WorkflowStatus.id == WorkflowTransition.to_status_id",
        foreign_keys=[to_status_id],
        lazy="selectin",
        viewonly=True,
    )
    required_position: Mapped[Position] = relationship(lazy="selectin", viewonly=True)


class Case(Base):
    """A file moving through a workflow. Created by alembic/versions/0006_cases.py.

    Change current_status_id only through workflow/service.py change_status(),
    which checks the move is allowed and writes the audit row.
    """

    __tablename__ = "cases"
    __table_args__ = (
        ForeignKeyConstraint(
            ["workflow_id", "current_status_id"],
            ["core.workflow_statuses.workflow_id", "core.workflow_statuses.id"],
            name="cases_status_fkey",
        ),
        Index("cases_created_by_idx", "created_by"),
        {"schema": "core"},
    )
    __mapper_args__ = {"eager_defaults": True}

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    workflow_id: Mapped[int] = mapped_column(SmallInteger)
    current_status_id: Mapped[int] = mapped_column(Integer)
    created_by: Mapped[int] = mapped_column(BigInteger, ForeignKey("core.users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    workflow: Mapped[Workflow] = relationship(
        primaryjoin="Workflow.id == Case.workflow_id",
        foreign_keys=[workflow_id],
        lazy="selectin",
        viewonly=True,
    )
    current_status: Mapped[WorkflowStatus] = relationship(
        primaryjoin="WorkflowStatus.id == Case.current_status_id",
        foreign_keys=[current_status_id],
        lazy="selectin",
        viewonly=True,
    )


class Delegation(Base):
    """One post letting another act for it. Created by alembic/versions/0010_delegations.py.

    Create and revoke only through workflow/delegation.py, which checks who may
    delegate and writes the audit rows.
    """

    __tablename__ = "delegations"
    __table_args__ = (
        CheckConstraint("from_position_id <> to_position_id", name="delegations_not_to_self"),
        CheckConstraint("starts_on <= ends_on", name="delegations_dates_in_order"),
        CheckConstraint(
            "(revoked_at IS NULL) = (revoked_by IS NULL)", name="delegations_revoked_complete"
        ),
        Index("delegations_to_position_idx", "to_position_id", "ends_on"),
        {"schema": "core"},
    )
    __mapper_args__ = {"eager_defaults": True}

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    from_position_id: Mapped[int] = mapped_column(SmallInteger, ForeignKey("core.positions.id"))
    to_position_id: Mapped[int] = mapped_column(SmallInteger, ForeignKey("core.positions.id"))
    workflow_id: Mapped[int | None] = mapped_column(SmallInteger, ForeignKey("core.workflows.id"))
    starts_on: Mapped[date] = mapped_column(Date)
    ends_on: Mapped[date] = mapped_column(Date)
    reason: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[int] = mapped_column(BigInteger, ForeignKey("core.users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_by: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("core.users.id"))

    from_position: Mapped[Position] = relationship(
        foreign_keys=[from_position_id], lazy="selectin", viewonly=True
    )
    to_position: Mapped[Position] = relationship(
        foreign_keys=[to_position_id], lazy="selectin", viewonly=True
    )
    workflow: Mapped[Workflow | None] = relationship(lazy="selectin", viewonly=True)


class SuccessionStep(Base):
    """One place in a post's line of succession. Created by alembic/versions/0013_succession_orders.py.

    Read by workflow/succession.py; written only by migrations.
    """

    __tablename__ = "succession_orders"
    __table_args__ = (
        CheckConstraint("rank >= 1", name="succession_orders_rank_positive"),
        CheckConstraint("successor_position_id <> position_id", name="succession_orders_not_self"),
        UniqueConstraint(
            "position_id",
            "workflow_id",
            "rank",
            name="succession_orders_rank_key",
            postgresql_nulls_not_distinct=True,
        ),
        UniqueConstraint(
            "position_id",
            "workflow_id",
            "successor_position_id",
            name="succession_orders_successor_key",
            postgresql_nulls_not_distinct=True,
        ),
        {"schema": "core"},
    )

    id: Mapped[int] = mapped_column(SmallInteger, Identity(), primary_key=True)
    position_id: Mapped[int] = mapped_column(SmallInteger, ForeignKey("core.positions.id"))
    workflow_id: Mapped[int | None] = mapped_column(SmallInteger, ForeignKey("core.workflows.id"))
    rank: Mapped[int] = mapped_column(SmallInteger)
    successor_position_id: Mapped[int] = mapped_column(SmallInteger, ForeignKey("core.positions.id"))


class Absence(Base):
    """A person away from work for a date range. Created by alembic/versions/0014_absences.py.

    Record and cancel only through workflow/absence.py, which checks who may do
    it and writes the audit rows.
    """

    __tablename__ = "absences"
    __table_args__ = (
        CheckConstraint("starts_on <= ends_on", name="absences_dates_in_order"),
        CheckConstraint(
            "(cancelled_at IS NULL) = (cancelled_by IS NULL)", name="absences_cancelled_complete"
        ),
        Index("absences_user_idx", "user_id", "ends_on"),
        {"schema": "core"},
    )
    __mapper_args__ = {"eager_defaults": True}

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("core.users.id"))
    starts_on: Mapped[date] = mapped_column(Date)
    ends_on: Mapped[date] = mapped_column(Date)
    reason: Mapped[str | None] = mapped_column(Text)
    recorded_by: Mapped[int] = mapped_column(BigInteger, ForeignKey("core.users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancelled_by: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("core.users.id"))


class CaseFlag(Base):
    """Something about a case that a post must look at. Created by alembic/versions/0016_case_flags.py.

    Raise and resolve only through workflow/flags.py, which writes the audit rows.
    """

    __tablename__ = "case_flags"
    __table_args__ = (
        CheckConstraint(
            "(resolved_at IS NULL) = (resolved_by IS NULL) AND (resolved_at IS NULL) = (resolution IS NULL)",
            name="case_flags_resolved_complete",
        ),
        Index("case_flags_open_idx", "case_id", postgresql_where=text("resolved_at IS NULL")),
        {"schema": "core"},
    )
    __mapper_args__ = {"eager_defaults": True}

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    case_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("core.cases.id"))
    code: Mapped[str] = mapped_column(Text)
    message: Mapped[str] = mapped_column(Text)
    details: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    for_position_id: Mapped[int] = mapped_column(SmallInteger, ForeignKey("core.positions.id"))
    blocking: Mapped[bool] = mapped_column(Boolean, server_default=true())
    raised_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    raised_by: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("core.users.id"))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolved_by: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("core.users.id"))
    resolution: Mapped[str | None] = mapped_column(Text)

    for_position: Mapped[Position] = relationship(lazy="selectin", viewonly=True)
