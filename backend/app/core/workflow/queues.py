"""Lists of cases: an applicant's own cases, and a staff member's queue.

The queue is "every open case where I can make a move right now", whichever
way I'm entitled to: my own post, a delegation to my post, or the succession
order. The final word is the engine's own available_transitions(), so the
queue can never show a case whose page then offers no button (or miss one).
To keep that affordable, cases are first narrowed in SQL to those whose next
step belongs to a post the user could possibly act as.
"""

from dataclasses import dataclass

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.identity.models import User
from app.core.workflow import history, service, summaries
from app.core.workflow.delegation import today
from app.core.workflow.models import Case, Delegation, SuccessionStep, WorkflowStatus, WorkflowTransition


@dataclass
class QueueItem:
    case: Case
    moves: list[service.PermittedMove]  # empty in an applicant's own list
    summary: str | None  # the module's one line, e.g. the goods
    applicant_name: str | None  # staff only
    applicant_message: str | None = None  # "my cases": why it was returned or rejected

    @property
    def days_waiting(self) -> int:
        return (today() - self.case.status_changed_at.date()).days


async def _summaries(session: AsyncSession, cases: list[Case]) -> dict[int, str]:
    by_workflow: dict[str, list[int]] = {}
    for case in cases:
        by_workflow.setdefault(case.workflow.code, []).append(case.id)
    return await summaries.summaries_for(session, by_workflow)


async def my_cases(session: AsyncSession, user: User) -> list[QueueItem]:
    """The cases this user applied for, or entered for a walk-in applicant, newest first."""
    cases = list(
        await session.scalars(
            select(Case)
            .where(or_(Case.created_by == user.id, Case.entered_by == user.id))
            .order_by(Case.created_at.desc(), Case.id.desc())
        )
    )
    found = await _summaries(session, cases)
    # One query per case: an applicant has a handful of cases, not hundreds.
    return [QueueItem(c, [], found.get(c.id), None, await history.current_message(session, c)) for c in cases]


async def _positions_i_might_act_as(session: AsyncSession, user: User) -> set[int]:
    """A generous superset of the posts whose moves this user could make today:
    their own, any delegated to them now, and any whose succession line names
    one of their posts. The exact rules are applied afterwards, per case."""
    held = {p.id for p in user.positions}
    if not held:
        return set()
    on = today()
    delegated = await session.scalars(
        select(Delegation.from_position_id).where(
            Delegation.to_position_id.in_(held),
            Delegation.revoked_at.is_(None),
            Delegation.starts_on <= on,
            Delegation.ends_on >= on,
        )
    )
    successions = await session.scalars(
        select(SuccessionStep.position_id).where(SuccessionStep.successor_position_id.in_(held))
    )
    return held | set(delegated) | set(successions)


async def queue(
    session: AsyncSession, user: User, *, status: str | None = None, workflow: str | None = None
) -> list[QueueItem]:
    """Open cases where this user can make a move now, longest-waiting first.

    `status` (a status code, e.g. "signed") and `workflow` narrow it, e.g. for
    Records' "Outgoing" tab.
    """
    if not service.is_staff(user):
        raise service.NotPermitted("Only Ministry staff have a queue.")
    positions = await _positions_i_might_act_as(session, user)
    if not positions:
        return []

    query = (
        select(Case)
        .join(WorkflowStatus, WorkflowStatus.id == Case.current_status_id)
        .where(
            ~WorkflowStatus.is_final,
            Case.current_status_id.in_(
                select(WorkflowTransition.from_status_id).where(
                    WorkflowTransition.required_position_id.in_(positions),
                    # Being able to put a mistake right isn't work waiting for you.
                    ~WorkflowTransition.is_correction,
                )
            ),
        )
        .order_by(Case.status_changed_at, Case.id)
    )
    if status:
        query = query.where(WorkflowStatus.code == status)
    if workflow:
        query = query.where(Case.workflow.has(code=workflow))

    items = []
    for case in await session.scalars(query):
        moves = [m for m in await service.available_transitions(session, case, user) if not m.transition.is_correction]
        if moves:
            items.append(QueueItem(case, moves, None, None))

    found = await _summaries(session, [i.case for i in items])
    applicants = {
        u.id: u.full_name
        for u in await session.scalars(select(User).where(User.id.in_({i.case.created_by for i in items})))
    }
    for item in items:
        item.summary = found.get(item.case.id)
        item.applicant_name = applicants.get(item.case.created_by)
    return items
