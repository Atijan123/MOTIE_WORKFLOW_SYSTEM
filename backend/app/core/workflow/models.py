from sqlalchemy import (
    Boolean,
    CheckConstraint,
    ForeignKey,
    ForeignKeyConstraint,
    Identity,
    Index,
    Integer,
    SmallInteger,
    Text,
    UniqueConstraint,
    false,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.identity.models import Role
from app.db.base import Base

# Tables created by alembic/versions/0004_workflow_definitions.py.
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
            "from_status_id", "to_status_id", "required_role_id", name="workflow_transitions_move_key"
        ),
        CheckConstraint("from_status_id <> to_status_id", name="workflow_transitions_no_self_loop"),
        {"schema": "core"},
    )

    id: Mapped[int] = mapped_column(Integer, Identity(), primary_key=True)
    workflow_id: Mapped[int] = mapped_column(SmallInteger)
    from_status_id: Mapped[int] = mapped_column(Integer)
    to_status_id: Mapped[int] = mapped_column(Integer)
    required_role_id: Mapped[int] = mapped_column(SmallInteger, ForeignKey("core.roles.id"))
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
    required_role: Mapped[Role] = relationship(lazy="selectin", viewonly=True)
