from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
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
)
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
