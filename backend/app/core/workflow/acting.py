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

from sqlalchemy import or_, select
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
class WhoActs:
    """Who takes an absent person's files, for one or more services."""

    position: str
    title: str
    holders: list[str]  # names of the people at work in that post
    basis: str  # "delegation", "succession", or "same_post" (another holder of their own post is at work)
    workflows: list[str] | None  # None = every service


@dataclass
class AbsenceView:
    id: int
    person: str
    posts: list[str]  # titles of the posts they hold
    starts_on: date
    ends_on: date
    reason: str | None  # only for the person themselves and for recorders
    may_cancel: bool  # the same rule as cancel_absence(), so the screen offers only what works
    recorded_by: str  # name of whoever entered it
    recorded_by_self: bool
    who_acts: list[WhoActs]  # empty: nobody (no delegation, nobody in the succession order at work)


async def _away_on(session: AsyncSession, on: date) -> set[int]:
    """Users with an absence covering this day."""
    return set(
        await session.scalars(
            select(Absence.user_id).where(
                Absence.cancelled_at.is_(None), Absence.starts_on <= on, Absence.ends_on >= on
            )
        )
    )


async def _who_acts(
    session: AsyncSession,
    person: User,
    on: date,
    away: set[int],
    holders: dict[int, list[int]],
    workflows: list[Workflow],
) -> list[tuple[int, str, list[str] | None]]:
    """(position id, basis, workflow codes or None) for each stand-in on day `on`.

    The engine's rules, for a given day instead of today: a delegation from the
    post comes first (delegation.is_delegated_away()); otherwise the first post
    in the succession order with a holder at work (succession.acting_successor()).
    """
    covered: dict[tuple[int, str], list[str]] = {}
    for post in sorted(person.positions, key=lambda p: p.id):
        if any(u != person.id and u not in away for u in holders.get(post.id, [])):
            covered[(post.id, "same_post")] = [w.code for w in workflows]
            continue
        for wf in workflows:
            delegation = await session.scalar(
                select(Delegation)
                .where(
                    Delegation.from_position_id == post.id,
                    Delegation.revoked_at.is_(None),
                    Delegation.starts_on <= on,
                    Delegation.ends_on >= on,
                    or_(Delegation.workflow_id.is_(None), Delegation.workflow_id == wf.id),
                )
                .order_by(Delegation.id)
                .limit(1)
            )
            if delegation:
                covered.setdefault((delegation.to_position_id, "delegation"), []).append(wf.code)
                continue
            for successor in await succession_order(session, post.id, wf.id):
                if any(u not in away for u in holders.get(successor, [])):
                    covered.setdefault((successor, "succession"), []).append(wf.code)
                    break
    every = {w.code for w in workflows}
    return [
        (position_id, basis, None if set(codes) == every else codes)
        for (position_id, basis), codes in covered.items()
    ]


async def current_absences(session: AsyncSession, user: User) -> list[AbsenceView]:
    """Everyone away now or later, soonest first. Reasons can be personal (sick
    leave), so other staff see who and when, not why.

    "Who acts" is worked out for the absence's first day, or today if it has
    started: later absences or delegations may change it after that.
    """
    absences = list(
        await session.scalars(
            select(Absence)
            .where(Absence.cancelled_at.is_(None), Absence.ends_on >= today())
            .order_by(Absence.starts_on, Absence.id)
        )
    )
    if not absences:
        return []
    positions = {p.id: p for p in await session.scalars(select(Position))}
    workflows = list(await session.scalars(select(Workflow).order_by(Workflow.id)))
    holders: dict[int, list[int]] = {}
    for row in (await session.execute(select(position_holders.c.position_id, position_holders.c.user_id))).all():
        holders.setdefault(row.position_id, []).append(row.user_id)
    user_ids = {a.user_id for a in absences} | {a.recorded_by for a in absences}
    user_ids |= {u for ids in holders.values() for u in ids}
    people = {u.id: u for u in await session.scalars(select(User).where(User.id.in_(user_ids)))}
    may_see_reasons = may_record_for_others(user)

    away_cache: dict[date, set[int]] = {}
    views = []
    for a in absences:
        on = max(a.starts_on, today())
        if on not in away_cache:
            away_cache[on] = await _away_on(session, on)
        away = away_cache[on]
        stand_ins = await _who_acts(session, people[a.user_id], on, away, holders, workflows)
        views.append(
            AbsenceView(
                id=a.id,
                person=people[a.user_id].full_name,
                posts=sorted(p.title for p in people[a.user_id].positions),
                starts_on=a.starts_on,
                ends_on=a.ends_on,
                reason=a.reason if may_see_reasons or a.user_id == user.id or a.recorded_by == user.id else None,
                may_cancel=a.user_id == user.id or may_see_reasons,
                recorded_by=people[a.recorded_by].full_name,
                recorded_by_self=a.recorded_by == a.user_id,
                who_acts=[
                    WhoActs(
                        position=positions[position_id].code,
                        title=positions[position_id].title,
                        holders=sorted(
                            people[u].full_name
                            for u in holders.get(position_id, [])
                            if u not in away and u != a.user_id
                        ),
                        basis=basis,
                        workflows=codes,
                    )
                    for position_id, basis, codes in stand_ins
                ],
            )
        )
    return views


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

