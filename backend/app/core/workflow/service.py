"""The workflow engine: the only code that creates cases or changes their status.

Every status change is checked against core.workflow_transitions and recorded
in core.audit_log in the same transaction.
"""

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit.service import record_event
from app.core.identity.models import User
from app.core.workflow.models import Case, Workflow, WorkflowStatus, WorkflowTransition

AUDIT_ENTITY = "case"


class WorkflowError(Exception):
    """Base class; the API turns each subclass into an HTTP status (see router.py)."""


class NotFound(WorkflowError):
    pass


class NotPermitted(WorkflowError):
    pass


class TransitionNotAllowed(WorkflowError):
    pass


def is_staff(user: User) -> bool:
    return bool(user.role_codes - {"applicant"})


def can_view(case: Case, user: User) -> bool:
    # [CONFIRM] Placeholder rule: the applicant who opened the case, or any
    # Ministry staff member. The Ministry may want staff limited to their own
    # directorate.
    return case.created_by == user.id or is_staff(user)


async def get_case(
    session: AsyncSession, case_id: int, user: User, *, for_update: bool = False
) -> Case:
    query = select(Case).where(Case.id == case_id)
    if for_update:
        # SELECT ... FOR UPDATE locks this case row until we commit. If two
        # officers act on the same case at once, the second waits, then sees the
        # first one's new status, instead of both moves succeeding.
        # populate_existing re-reads the row even if this session already had it,
        # so we never decide based on a stale status.
        query = query.with_for_update().execution_options(populate_existing=True)
    case = await session.scalar(query)
    if case is None or not can_view(case, user):
        # One answer for "doesn't exist" and "not yours", so nobody can probe
        # case ids to learn which exist.
        raise NotFound("Case not found.")
    return case


async def start_case(session: AsyncSession, *, workflow_code: str, actor: User) -> Case:
    workflow = await session.scalar(select(Workflow).where(Workflow.code == workflow_code))
    if workflow is None:
        raise NotFound(f"No workflow called '{workflow_code}'.")
    if workflow.start_role.code not in actor.role_codes:
        raise NotPermitted("Your role can't open this kind of case.")

    initial = await session.scalar(
        select(WorkflowStatus).where(
            WorkflowStatus.workflow_id == workflow.id, WorkflowStatus.is_initial
        )
    )
    case = Case(workflow_id=workflow.id, current_status_id=initial.id, created_by=actor.id)
    session.add(case)
    await session.flush()  # sends the INSERT now, so case.id exists for the audit row
    record_event(
        session,
        actor=actor,
        action="case.created",
        entity_type=AUDIT_ENTITY,
        entity_id=case.id,
        details={"workflow": workflow.code, "status": initial.code},
    )
    await session.commit()
    await session.refresh(case, ["workflow", "current_status"])
    return case


async def available_transitions(
    session: AsyncSession, case: Case, user: User
) -> list[WorkflowTransition]:
    """The moves this user may make on this case right now (the buttons to show)."""
    result = await session.scalars(
        select(WorkflowTransition)
        .where(
            WorkflowTransition.from_status_id == case.current_status_id,
            WorkflowTransition.required_position_id.in_([p.id for p in user.positions]),
        )
        .order_by(WorkflowTransition.id)
    )
    # The same move can be allowed for two of the user's posts; list it once.
    moves: dict[int, WorkflowTransition] = {}
    for move in result:
        moves.setdefault(move.to_status_id, move)
    return list(moves.values())


async def change_status(
    session: AsyncSession,
    *,
    case_id: int,
    to_status_code: str,
    actor: User,
    comment: str | None = None,
) -> Case:
    case = await get_case(session, case_id, actor, for_update=True)
    from_status = case.current_status

    # Every row that allows this exact move, whatever the position.
    moves = (
        await session.scalars(
            select(WorkflowTransition)
            .join(WorkflowStatus, WorkflowStatus.id == WorkflowTransition.to_status_id)
            .where(
                WorkflowTransition.from_status_id == case.current_status_id,
                WorkflowStatus.code == to_status_code,
            )
        )
    ).all()
    if not moves:
        raise TransitionNotAllowed(
            f"A case can't move from '{from_status.code}' to '{to_status_code}'."
        )
    held = {p.id for p in actor.positions}
    move = next((m for m in moves if m.required_position_id in held), None)
    if move is None:
        raise NotPermitted("None of your positions can make this move.")

    case.current_status_id = move.to_status_id
    case.updated_at = func.now()
    record_event(
        session,
        actor=actor,
        action="case.status_changed",
        entity_type=AUDIT_ENTITY,
        entity_id=case.id,
        details={
            "from": from_status.code,
            "to": to_status_code,
            "transition": move.name,
            "as_position": move.required_position.code,
            "comment": comment,
        },
    )
    # Status change and audit row are committed together, or not at all.
    await session.commit()
    await session.refresh(case, ["current_status", "updated_at"])
    return case
