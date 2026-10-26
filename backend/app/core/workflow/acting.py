"""Who is acting for whom, for the acting banner and the absences screen (S11).

- acting_now(): the posts I'm acting for today, and on what basis. The banner
  on every screen: "You are acting for the Permanent Secretary (absent ...)".
- cover_for_me(): for each of my posts, who would act if I'm away: my
  delegations, and the succession line per workflow.
- current_absences(): who is away now or soon, for all staff.
- choices(): the posts (with their holders) and workflows the S11 forms pick from.

These use the same rules as the engine (delegation.py, succession.py), so the
banner says exactly what the buttons will allow.
"""

from dataclasses import dataclass, field
from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.identity.models import Position, User, position_holders
from app.core.workflow.absence import may_record_for_others
from app.core.workflow.delegation import is_delegated_away, today
from app.core.workflow.models import Absence, Delegation, SuccessionStep, Workflow
from app.core.workflow.succession import acting_successor, succession_order


@dataclass
class AwayPeriod:
    person: str
    starts_on: date
    ends_on: date


@dataclass
class ActingNow:
    position: str  # code of the post I'm acting for
    title: str
    basis: str  # "delegation" or "succession"
    workflows: list[str] | None  # None = every workflow
    absences: list[AwayPeriod] = field(default_factory=list)  # succession: who is away, until when
    delegation_starts_on: date | None = None  # delegation: its dates
    delegation_ends_on: date | None = None


async def _names(session: AsyncSession, user_ids: set[int]) -> dict[int, str]:
    if not user_ids:
        return {}
    return {u.id: u.full_name for u in await session.scalars(select(User).where(User.id.in_(user_ids)))}


async def acting_now(session: AsyncSession, user: User) -> list[ActingNow]:
    held = {p.id for p in user.positions}
    if not held:
        return []
    positions = {p.id: p for p in await session.scalars(select(Position))}
    workflows = list(await session.scalars(select(Workflow).order_by(Workflow.id)))
    found: list[ActingNow] = []

    # Delegations to one of my posts, in force today.
    on = today()
    for d in await session.scalars(
        select(Delegation)
        .where(
            Delegation.to_position_id.in_(held),
            Delegation.revoked_at.is_(None),
            Delegation.starts_on <= on,
            Delegation.ends_on >= on,
        )
        .order_by(Delegation.id)
    ):
        found.append(
            ActingNow(
                position=positions[d.from_position_id].code,
                title=positions[d.from_position_id].title,
                basis="delegation",
                workflows=[w.code for w in workflows if w.id == d.workflow_id] if d.workflow_id else None,
                delegation_starts_on=d.starts_on,
                delegation_ends_on=d.ends_on,
            )
        )

    # Succession: posts whose line names one of mine. Ask the engine's own rule
    # for each workflow, because a line can differ per workflow (the Director's
    # stand-in is for ETLS only) and a delegation blocks succession.
    candidates = set(
        await session.scalars(
            select(SuccessionStep.position_id).where(SuccessionStep.successor_position_id.in_(held))
        )
    ) - held
    for position_id in sorted(candidates):
        covered: list[str] = []
        away = {}
        for wf in workflows:
            if await is_delegated_away(session, position_id, wf.id):
                continue
            succession = await acting_successor(session, position_id, wf.id)
            if succession and succession.acting_position_id in held:
                covered.append(wf.code)
                away.update({a.id: a for a in succession.absences})
        if covered:
            names = await _names(session, {a.user_id for a in away.values()})
            found.append(
                ActingNow(
                    position=positions[position_id].code,
                    title=positions[position_id].title,
                    basis="succession",
                    workflows=None if len(covered) == len(workflows) else covered,
                    absences=[
                        AwayPeriod(names.get(a.user_id, "?"), a.starts_on, a.ends_on)
                        for a in sorted(away.values(), key=lambda a: (a.starts_on, a.id))
                    ],
                )
            )
    return found


@dataclass
class StandIn:
    position: str
    title: str
    holders: list[str]  # names of the people who hold it now


@dataclass
class SuccessionLine:
    workflow: str
    line: list[StandIn]  # first in line first


@dataclass
class MyDelegation:
    id: int
    to_position: str
    to_title: str
    workflow: str | None
    starts_on: date
    ends_on: date


@dataclass
class CoverForPost:
    position: str
    title: str
    delegations: list[MyDelegation]  # current and upcoming; these come first
    succession: list[SuccessionLine]  # otherwise, per workflow


async def cover_for_me(session: AsyncSession, user: User) -> list[CoverForPost]:
    positions = {p.id: p for p in await session.scalars(select(Position))}
    workflows = list(await session.scalars(select(Workflow).order_by(Workflow.id)))
    holder_rows = (await session.execute(select(position_holders.c.position_id, position_holders.c.user_id))).all()
    names = await _names(session, {r.user_id for r in holder_rows})
    holders: dict[int, list[str]] = {}
    for row in holder_rows:
        holders.setdefault(row.position_id, []).append(names[row.user_id])

    result = []
    for mine in sorted(user.positions, key=lambda p: p.id):
        delegations = await session.scalars(
            select(Delegation)
            .where(
                Delegation.from_position_id == mine.id,
                Delegation.revoked_at.is_(None),
                Delegation.ends_on >= today(),
            )
            .order_by(Delegation.starts_on, Delegation.id)
        )
        lines = []
        for wf in workflows:
            order = await succession_order(session, mine.id, wf.id)
            if order:
                lines.append(
                    SuccessionLine(
                        wf.code,
                        [StandIn(positions[p].code, positions[p].title, sorted(holders.get(p, []))) for p in order],
                    )
                )
        result.append(
            CoverForPost(
                position=mine.code,
                title=mine.title,
                delegations=[
                    MyDelegation(
                        d.id,
                        positions[d.to_position_id].code,
                        positions[d.to_position_id].title,
                        next((w.code for w in workflows if w.id == d.workflow_id), None),
                        d.starts_on,
                        d.ends_on,
                    )
                    for d in delegations
                ],
                succession=lines,
            )
        )
    return result


@dataclass
class AbsenceView:
    id: int
    person: str
    posts: list[str]  # titles of the posts they hold
    starts_on: date
    ends_on: date
    reason: str | None  # only for the person themselves and for recorders
    may_cancel: bool  # the same rule as cancel_absence(), so the screen offers only what works


async def current_absences(session: AsyncSession, user: User) -> list[AbsenceView]:
    """Everyone away now or later, soonest first. Reasons can be personal (sick
    leave), so other staff see who and when, not why."""
    absences = list(
        await session.scalars(
            select(Absence)
            .where(Absence.cancelled_at.is_(None), Absence.ends_on >= today())
            .order_by(Absence.starts_on, Absence.id)
        )
    )
    people = {
        u.id: u
        for u in await session.scalars(select(User).where(User.id.in_({a.user_id for a in absences})))
    }
    may_see_reasons = may_record_for_others(user)
    return [
        AbsenceView(
            id=a.id,
            person=people[a.user_id].full_name,
            posts=sorted(p.title for p in people[a.user_id].positions),
            starts_on=a.starts_on,
            ends_on=a.ends_on,
            reason=a.reason if may_see_reasons or a.user_id == user.id or a.recorded_by == user.id else None,
            may_cancel=a.user_id == user.id or may_see_reasons,
        )
        for a in absences
    ]


@dataclass
class Holder:
    user_id: int
    name: str


@dataclass
class PostChoice:
    code: str
    title: str
    holders: list[Holder]  # an empty post can still be delegated to; nobody can act until it's filled


@dataclass
class WorkflowChoice:
    code: str
    name: str


@dataclass
class Choices:
    posts: list[PostChoice]
    workflows: list[WorkflowChoice]


async def choices(session: AsyncSession) -> Choices:
    """Every post with its holders, and every workflow: what S11's forms pick from
    ("delegate to which post", "for which service", "who is away")."""
    holder_rows = (await session.execute(select(position_holders.c.position_id, position_holders.c.user_id))).all()
    names = await _names(session, {r.user_id for r in holder_rows})
    holders: dict[int, list[Holder]] = {}
    for row in holder_rows:
        holders.setdefault(row.position_id, []).append(Holder(row.user_id, names[row.user_id]))
    posts = [
        PostChoice(p.code, p.title, sorted(holders.get(p.id, []), key=lambda h: h.name))
        for p in await session.scalars(select(Position).order_by(Position.title))
    ]
    workflows = [WorkflowChoice(w.code, w.name) for w in await session.scalars(select(Workflow).order_by(Workflow.name))]
    return Choices(posts, workflows)

