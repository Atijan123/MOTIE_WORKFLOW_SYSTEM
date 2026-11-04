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
    # Case references are "<prefix>/<year>/<number>", e.g. MOTIE/ETLS/FL/2026/0001 (0024).
    reference_prefix: Mapped[str] = mapped_column(Text, unique=True)
    # The post whose holders may open a case for an applicant who came in person (0032).
    walk_in_position_id: Mapped[int | None] = mapped_column(SmallInteger, ForeignKey("core.positions.id"))

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
    # What applicants see instead of `code` and `name` (0023).
    applicant_label: Mapped[str] = mapped_column(Text)
    applicant_explanation: Mapped[str | None] = mapped_column(Text)
    # The applicant may still change the form in this status, e.g. a draft (0026).
    applicant_editable: Mapped[bool] = mapped_column(Boolean, server_default=false())
    # The timeline's wording when the case comes back here after a hidden
    # correction took it away, e.g. "Corrected letter issued" (0030).
    applicant_label_corrected: Mapped[str | None] = mapped_column(Text)


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
        CheckConstraint(
            "by_applicant = (required_position_id IS NULL)", name="workflow_transitions_post_or_applicant"
        ),
        CheckConstraint(
            "applies_when IS NULL OR ("
            "jsonb_typeof(applies_when) = 'object' "
            "AND applies_when ?& array['field', 'op', 'value'] "
            "AND applies_when->>'op' IN ('equals', 'not_equals', 'contains'))",
            name="workflow_transitions_applies_when_shape",
        ),
        {"schema": "core"},
    )

    id: Mapped[int] = mapped_column(Integer, Identity(), primary_key=True)
    workflow_id: Mapped[int] = mapped_column(SmallInteger)
    from_status_id: Mapped[int] = mapped_column(Integer)
    to_status_id: Mapped[int] = mapped_column(Integer)
    # The post whose holders may make this move (or anyone acting for that post).
    # Empty for the applicant's own moves, such as "Submit" (0026).
    required_position_id: Mapped[int | None] = mapped_column(SmallInteger, ForeignKey("core.positions.id"))
    by_applicant: Mapped[bool] = mapped_column(Boolean, server_default=false())
    name: Mapped[str] = mapped_column(Text)
    # The move needs a written reason (the comment), e.g. cancelling a signed letter (0022).
    requires_comment: Mapped[bool] = mapped_column(Boolean, server_default=false())
    # How the applicant's timeline describes this move (0023): its own wording,
    # or the new status's label when empty; hidden entirely when not visible.
    applicant_event: Mapped[str | None] = mapped_column(Text)
    applicant_visible: Mapped[bool] = mapped_column(Boolean, server_default=true())
    # The move needs a message to the applicant, e.g. a return or a rejection (0027).
    requires_applicant_message: Mapped[bool] = mapped_column(Boolean, server_default=false())
    # May be made while a blocking flag holds the case, and resolves it (0029).
    allowed_on_hold: Mapped[bool] = mapped_column(Boolean, server_default=false())
    # Puts a mistake right (cancelling a letter): may leave a final status, and
    # puts the case in nobody's queue (0030).
    is_correction: Mapped[bool] = mapped_column(Boolean, server_default=false())
    # The move is only this case's move when the condition holds against the
    # module's facts, e.g. "HS heading is 2523" (0040). Empty = always. Tested
    # by service.applicable().
    applies_when: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    # Only holders of the post itself: no delegation, succession or signatory
    # list (0040), e.g. "only the Minister or the PS signs a cement letter".
    own_post_only: Mapped[bool] = mapped_column(Boolean, server_default=false())

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
    required_position: Mapped[Position | None] = relationship(lazy="selectin", viewonly=True)


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
        Index("cases_status_idx", "current_status_id", "status_changed_at"),  # queues (0025)
        {"schema": "core"},
    )
    __mapper_args__ = {"eager_defaults": True}

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    workflow_id: Mapped[int] = mapped_column(SmallInteger)
    current_status_id: Mapped[int] = mapped_column(Integer)
    created_by: Mapped[int] = mapped_column(BigInteger, ForeignKey("core.users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    # The tracking number, set when the applicant submits (0024); null for a draft.
    reference: Mapped[str | None] = mapped_column(Text, unique=True)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # When it entered its current status: queues' "waiting since" (0025). Set
    # only by the engine, so editing a draft doesn't reset it.
    status_changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    # A walk-in: the staff member who typed it in for the applicant (0032).
    # created_by is still the applicant, whose case it is.
    entered_by: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("core.users.id"))

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


class SignatoryList(Base):
    """A named list of people who may sign for an absent post (0040). Written by migrations."""

    __tablename__ = "signatory_lists"
    __table_args__ = {"schema": "core"}

    id: Mapped[int] = mapped_column(SmallInteger, Identity(), primary_key=True)
    code: Mapped[str] = mapped_column(Text, unique=True)
    name: Mapped[str] = mapped_column(Text)
    absence_wording: Mapped[str] = mapped_column(Text)  # e.g. "in the Director's absence"


class AuthorisedSignatory(Base):
    """One person's time on a signatory list (0040). Add and remove only through
    workflow/signatories.py, which checks who may and writes the audit rows."""

    __tablename__ = "authorised_signatories"
    __table_args__ = (
        CheckConstraint(
            "(removed_at IS NULL) = (removed_by IS NULL)", name="authorised_signatories_removed_complete"
        ),
        Index(
            "authorised_signatories_current_key",
            "list_id",
            "user_id",
            unique=True,
            postgresql_where=text("removed_at IS NULL"),
        ),
        {"schema": "core"},
    )
    __mapper_args__ = {"eager_defaults": True}

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    list_id: Mapped[int] = mapped_column(SmallInteger, ForeignKey("core.signatory_lists.id"))
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("core.users.id"))
    added_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    added_by: Mapped[int] = mapped_column(BigInteger, ForeignKey("core.users.id"))
    removed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    removed_by: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("core.users.id"))


class SignatoryRule(Base):
    """In this workflow, while every holder of this post is away, the people on
    this list act for it instead of the succession order (0040). Written by migrations."""

    __tablename__ = "signatory_rules"
    __table_args__ = {"schema": "core"}

    workflow_id: Mapped[int] = mapped_column(SmallInteger, ForeignKey("core.workflows.id"), primary_key=True)
    position_id: Mapped[int] = mapped_column(SmallInteger, ForeignKey("core.positions.id"), primary_key=True)
    list_id: Mapped[int] = mapped_column(SmallInteger, ForeignKey("core.signatory_lists.id"))


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


class TransitionCheck(Base):
    """A named check that must pass before a move. Created by alembic/versions/0018_transition_checks.py.

    The name is data; the function behind it is registered in workflow/checks.py.
    """

    __tablename__ = "transition_checks"
    __table_args__ = {"schema": "core"}

    transition_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("core.workflow_transitions.id"), primary_key=True
    )
    check_code: Mapped[str] = mapped_column(Text, primary_key=True)
    # Its findings are shown and recorded, but never stop the move (0028).
    warn_only: Mapped[bool] = mapped_column(Boolean, server_default=false())
    # False when it checks something sent with the move itself (a date), which
    # the dry run behind `blocked_by` can't know yet (0030).
    in_dry_run: Mapped[bool] = mapped_column(Boolean, server_default=true())


class TransitionEffect(Base):
    """A named effect a move sets off. Created by alembic/versions/0019_issued_documents.py.

    The name is data; the function behind it is registered in workflow/effects.py.
    """

    __tablename__ = "transition_effects"
    __table_args__ = {"schema": "core"}

    transition_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("core.workflow_transitions.id"), primary_key=True
    )
    effect_code: Mapped[str] = mapped_column(Text, primary_key=True)


class ChecklistItem(Base):
    """Something an officer ticks at a step, e.g. "exporter is on the ECOWAS list" (0029)."""

    __tablename__ = "checklist_items"
    __table_args__ = (
        ForeignKeyConstraint(
            ["workflow_id", "status_id"],
            ["core.workflow_statuses.workflow_id", "core.workflow_statuses.id"],
            name="checklist_items_status_fkey",
        ),
        UniqueConstraint("workflow_id", "code", name="checklist_items_code_key"),
        {"schema": "core"},
    )

    id: Mapped[int] = mapped_column(SmallInteger, Identity(), primary_key=True)
    workflow_id: Mapped[int] = mapped_column(SmallInteger)
    status_id: Mapped[int] = mapped_column(Integer)  # the step at which it's ticked
    code: Mapped[str] = mapped_column(Text)
    label: Mapped[str] = mapped_column(Text)
    sort_order: Mapped[int] = mapped_column(SmallInteger)


class CaseTick(Base):
    """One ticked item on one case (0029). Change through workflow/checklist.py, which audits it."""

    __tablename__ = "case_ticks"
    __table_args__ = {"schema": "core"}
    __mapper_args__ = {"eager_defaults": True}

    case_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("core.cases.id"), primary_key=True)
    item_id: Mapped[int] = mapped_column(SmallInteger, ForeignKey("core.checklist_items.id"), primary_key=True)
    ticked_by: Mapped[int] = mapped_column(BigInteger, ForeignKey("core.users.id"))
    ticked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ReferenceCounter(Base):
    """The last case reference number used, per workflow per year (0024)."""

    __tablename__ = "reference_counters"
    __table_args__ = (
        CheckConstraint("last_number > 0", name="reference_counters_positive"),
        {"schema": "core"},
    )

    workflow_id: Mapped[int] = mapped_column(SmallInteger, ForeignKey("core.workflows.id"), primary_key=True)
    year: Mapped[int] = mapped_column(SmallInteger, primary_key=True)
    last_number: Mapped[int] = mapped_column(Integer)
