"""The workflow engine: the only code that creates cases or changes their status.

Every status change is checked against core.workflow_transitions and recorded
in core.audit_log in the same transaction.
"""

from typing import NamedTuple

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit.service import record_event
from app.core.identity.models import User
from app.core.workflow.delegation import active_delegations_to, is_delegated_away
from app.core.workflow.errors import (  # noqa: F401  (re-exported: callers use service.NotFound etc.)
    AlreadyCancelled,
    AlreadyRevoked,
    InvalidAbsence,
    InvalidDelegation,
    NotFound,
    NotPermitted,
    TransitionNotAllowed,
    WorkflowError,
)
from app.core.workflow.models import Case, Delegation, Workflow, WorkflowStatus, WorkflowTransition
from app.core.workflow.succession import Succession, acting_successor

AUDIT_ENTITY = "case"


class PermittedMove(NamedTuple):
    """A move this user may make, and on what basis:
    - their own post (delegation and succession both None);
    - a delegation from the required post to one of theirs (`delegation`);
    - the succession order, because the required post's holders are away (`succession`).
    """

    transition: WorkflowTransition
    delegation: Delegation | None = None
    succession: Succession | None = None

    @property
    def basis(self) -> str:
        return "delegation" if self.delegation else "succession" if self.succession else "own"

    @property
    def on_behalf_of(self) -> str | None:
        """The post whose step this is, when the user acts for it ("acting for")."""
        return None if self.basis == "own" else self.transition.required_position.code


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
    """Open a case of a workflow that needs no module form (POST /cases)."""
    case = await open_case(session, workflow_code=workflow_code, actor=actor, module=None)
    await session.commit()
    await session.refresh(case, ["workflow", "current_status"])
    return case


async def open_case(
    session: AsyncSession, *, workflow_code: str, actor: User, module: str | None
) -> Case:
    """Add a new case and its audit row to the current transaction. Does NOT commit.

    A module calls this with its own name, saves its form rows, then commits
    once, so a case can never exist without its form. `module` must match the
    workflow's opened_by_module: the generic endpoint can't open module cases.
    """
    workflow = await session.scalar(select(Workflow).where(Workflow.code == workflow_code))
    if workflow is None:
        raise NotFound(f"No workflow called '{workflow_code}'.")
    if workflow.opened_by_module != module:
        raise NotPermitted(
            f"Cases of '{workflow_code}' are opened through the {workflow.opened_by_module} module."
        )
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
    return case


async def _permitted(
    session: AsyncSession, case: Case, user: User, transitions: list[WorkflowTransition]
) -> list[PermittedMove]:
    """Which of these transitions the user may make, best basis first: their own
    posts, then a personal delegation, then the succession order."""
    held = {p.id for p in user.positions}
    own = [PermittedMove(t) for t in transitions if t.required_position_id in held]
    rest = [t for t in transitions if t.required_position_id not in held]
    if not rest:
        return own  # nothing left that a delegation or succession could add

    acting_for = await active_delegations_to(session, user, case.workflow_id)
    delegated = [
        PermittedMove(t, delegation=acting_for[t.required_position_id])
        for t in rest
        if t.required_position_id in acting_for
    ]

    succeeded = []
    for t in rest:
        if t.required_position_id in acting_for:
            continue
        # A personal delegation takes priority: if the post chose who acts for it,
        # the standing succession order doesn't apply, even to its first in line.
        if await is_delegated_away(session, t.required_position_id, case.workflow_id):
            continue
        succession = await acting_successor(session, t.required_position_id, case.workflow_id)
        if succession and succession.acting_position_id in held:
            succeeded.append(PermittedMove(t, succession=succession))
    return own + delegated + succeeded


async def available_transitions(session: AsyncSession, case: Case, user: User) -> list[PermittedMove]:
    """The moves this user may make on this case right now (the buttons to show)."""
    transitions = (
        await session.scalars(
            select(WorkflowTransition)
            .where(WorkflowTransition.from_status_id == case.current_status_id)
            .order_by(WorkflowTransition.id)
        )
    ).all()
    # The same move can be allowed through two posts; list it once, preferring
    # the user's own post over acting for someone else.
    moves: dict[int, PermittedMove] = {}
    for move in await _permitted(session, case, user, list(transitions)):
        moves.setdefault(move.transition.to_status_id, move)
    return sorted(moves.values(), key=lambda m: m.transition.id)


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
    # Own posts come first in the list, so acting for someone else is only used
    # when the actor can't make the move in their own right.
    permitted = await _permitted(session, case, actor, list(moves))
    if not permitted:
        raise NotPermitted("None of your positions can make this move.")
    chosen = permitted[0]
    move, delegation, succession = chosen
    if delegation:
        acting_from = delegation.to_position.code
    elif succession:
        acting_from = next(p.code for p in actor.positions if p.id == succession.acting_position_id)
    else:
        acting_from = move.required_position.code

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
            # The post the actor acted from, whose step it was if not their own
            # ("acting for"), and why they could: "own", "delegation" or
            # "succession". Together: "PS, acting for the Minister, who is absent".
            "as_position": acting_from,
            "on_behalf_of": chosen.on_behalf_of,
            "basis": chosen.basis,
            "delegation_id": delegation.id if delegation else None,
            "absence_ids": [a.id for a in succession.absences] if succession else [],
            "comment": comment,
        },
    )
    # Status change and audit row are committed together, or not at all.
    await session.commit()
    await session.refresh(case, ["current_status", "updated_at"])
    return case
