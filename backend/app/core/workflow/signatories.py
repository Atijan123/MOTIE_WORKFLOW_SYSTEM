"""Authorised signatories: named people who act for a post while all its holders are away (S12).

For some posts, in some workflows, the succession order doesn't decide who
signs in the post's absence. A list of named people does: while every holder
of the Director of Industry and Investment is recorded absent, anyone on the
"director_absence" list may make the Director's moves on facility letters and
ETLS approvals (core.signatory_rules says which workflows and which post).

- The list holds people, not posts: being DPS doesn't put you on it.
- Everyone on it sees the step in their queue. Whoever acts first "claims" it:
  change_status() locks the case row, so a second signatory pressing at the
  same moment waits, then finds the case already moved and is refused.
- Only someone with the signatory_admin role (the Director's office) changes
  a list. Every addition and removal is in the audit log; removals keep the
  row, so the record of who could sign when stays complete.

The engine (service.py) calls acting_signatory() where it would otherwise use
the succession order.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import NamedTuple

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit.service import record_event
from app.core.identity.models import Position, User
from app.core.workflow.absence import absences_today
from app.core.workflow.errors import AlreadyRevoked, InvalidValue, NotFound, NotPermitted
from app.core.workflow.models import Absence, AuthorisedSignatory, SignatoryList, SignatoryRule, Workflow
from app.core.workflow.succession import presence

AUDIT_ENTITY = "signatory"
ADMIN_ROLE = "signatory_admin"


def is_admin(user: User) -> bool:
    return ADMIN_ROLE in user.role_codes


def _is_staff(user: User) -> bool:
    return bool(user.role_codes - {"applicant"})


class Signatory(NamedTuple):
    """Why this user may act for the post: their place on the list, and the
    absences of the post's holders that make the list apply."""

    membership: AuthorisedSignatory
    list: SignatoryList
    absences: list[Absence]


async def rule_for(session: AsyncSession, workflow_id: int, position_id: int) -> SignatoryRule | None:
    return await session.get(SignatoryRule, (workflow_id, position_id))


async def _membership(session: AsyncSession, list_id: int, user_id: int) -> AuthorisedSignatory | None:
    return await session.scalar(
        select(AuthorisedSignatory).where(
            AuthorisedSignatory.list_id == list_id,
            AuthorisedSignatory.user_id == user_id,
            AuthorisedSignatory.removed_at.is_(None),
        )
    )


async def acting_signatory(
    session: AsyncSession, rule: SignatoryRule, user: User
) -> Signatory | None:
    """May this user act for the rule's post today, as an authorised signatory?

    Yes when every holder of the post is recorded absent today (the same test
    as succession: a vacant post isn't "absent" [CONFIRM]), the user is on the
    list now, and the user isn't recorded absent themselves.
    """
    if not user.is_active or not _is_staff(user):
        return None
    present, away = await presence(session, rule.position_id)
    if present or not away:
        return None
    membership = await _membership(session, rule.list_id, user.id)
    if membership is None:
        return None
    # [CONFIRM] A signatory who is away doesn't get the step, like a successor
    # post whose holders are all away is skipped.
    if await absences_today(session, [user.id]):
        return None
    return Signatory(membership, await session.get(SignatoryList, rule.list_id), away)


async def posts_i_may_sign_for(session: AsyncSession, user: User) -> set[int]:
    """Posts with a signatory list this user is on now, in any workflow. A
    generous superset for the queue's first narrowing (queues.py)."""
    return set(
        await session.scalars(
            select(SignatoryRule.position_id)
            .join(AuthorisedSignatory, AuthorisedSignatory.list_id == SignatoryRule.list_id)
            .where(AuthorisedSignatory.user_id == user.id, AuthorisedSignatory.removed_at.is_(None))
        )
    )


async def lists_for_post(session: AsyncSession, position_id: int) -> list[tuple[Workflow, SignatoryList]]:
    """(workflow, list) for each workflow whose signing for this post goes by a list."""
    rows = await session.execute(
        select(Workflow, SignatoryList)
        .join(SignatoryRule, SignatoryRule.workflow_id == Workflow.id)
        .join(SignatoryList, SignatoryList.id == SignatoryRule.list_id)
        .where(SignatoryRule.position_id == position_id)
        .order_by(Workflow.id)
    )
    return [(w, l) for w, l in rows.all()]


async def current_members(session: AsyncSession, list_id: int) -> list[User]:
    return list(
        await session.scalars(
            select(User)
            .join(AuthorisedSignatory, AuthorisedSignatory.user_id == User.id)
            .where(AuthorisedSignatory.list_id == list_id, AuthorisedSignatory.removed_at.is_(None))
            .order_by(User.full_name)
        )
    )


# --- S12: keeping the lists ---


@dataclass
class UsedFor:
    workflow: str
    workflow_name: str
    position: str
    position_title: str


@dataclass
class Member:
    id: int
    user_id: int
    name: str
    posts: list[str]  # titles of the posts they hold, for recognising them
    added_at: datetime
    added_by: str
    removed_at: datetime | None
    removed_by: str | None


@dataclass
class ListView:
    code: str
    name: str
    absence_wording: str
    used_for: list[UsedFor]
    current: list[Member]  # by name
    past: list[Member]  # most recently removed first


def _require_admin(user: User) -> None:
    if not is_admin(user):
        raise NotPermitted("Only the Director's office (signatory_admin) keeps the signatories lists.")


async def overview(session: AsyncSession, user: User) -> list[ListView]:
    """Every list, where it applies, who is on it and who was (S12)."""
    _require_admin(user)
    lists = list(await session.scalars(select(SignatoryList).order_by(SignatoryList.id)))
    rules = (
        await session.execute(
            select(SignatoryRule, Workflow, Position)
            .join(Workflow, Workflow.id == SignatoryRule.workflow_id)
            .join(Position, Position.id == SignatoryRule.position_id)
            .order_by(Workflow.name)
        )
    ).all()
    memberships = list(await session.scalars(select(AuthorisedSignatory).order_by(AuthorisedSignatory.id)))
    user_ids = {m.user_id for m in memberships} | {m.added_by for m in memberships}
    user_ids |= {m.removed_by for m in memberships if m.removed_by}
    people = {u.id: u for u in await session.scalars(select(User).where(User.id.in_(user_ids)))} if user_ids else {}

    def member(m: AuthorisedSignatory) -> Member:
        person = people[m.user_id]
        return Member(
            id=m.id,
            user_id=m.user_id,
            name=person.full_name,
            posts=sorted(p.title for p in person.positions),
            added_at=m.added_at,
            added_by=people[m.added_by].full_name,
            removed_at=m.removed_at,
            removed_by=people[m.removed_by].full_name if m.removed_by else None,
        )

    views = []
    for lst in lists:
        mine = [member(m) for m in memberships if m.list_id == lst.id]
        views.append(
            ListView(
                code=lst.code,
                name=lst.name,
                absence_wording=lst.absence_wording,
                used_for=[
                    UsedFor(w.code, w.name, p.code, p.title) for rule, w, p in rules if rule.list_id == lst.id
                ],
                current=sorted((m for m in mine if m.removed_at is None), key=lambda m: m.name),
                past=sorted((m for m in mine if m.removed_at is not None), key=lambda m: m.removed_at, reverse=True),
            )
        )
    return views


@dataclass
class Candidate:
    user_id: int
    name: str
    posts: list[str]


async def candidates(session: AsyncSession, user: User) -> list[Candidate]:
    """Staff who could be added: active, not applicants. (Who is already on a
    list is in overview(); the screen leaves them out.)"""
    _require_admin(user)
    staff = [
        u
        for u in await session.scalars(select(User).where(User.is_active).order_by(User.full_name))
        if _is_staff(u)
    ]
    return [Candidate(u.id, u.full_name, sorted(p.title for p in u.positions)) for u in staff]


async def _list(session: AsyncSession, code: str) -> SignatoryList:
    found = await session.scalar(select(SignatoryList).where(SignatoryList.code == code))
    if found is None:
        raise NotFound(f"No signatories list called '{code}'.")
    return found


async def add_signatory(session: AsyncSession, *, actor: User, list_code: str, user_id: int) -> AuthorisedSignatory:
    """Put a named staff member on a list, from now on."""
    _require_admin(actor)
    lst = await _list(session, list_code)
    person = await session.get(User, user_id)
    if person is None or not person.is_active:
        raise NotFound("User not found.")
    if not _is_staff(person):
        raise InvalidValue("Only Ministry staff can be authorised signatories.")
    # [CONFIRM] Nobody puts themselves on the list: someone else in the
    # Director's office must, so every signing power has a second pair of eyes.
    if person.id == actor.id:
        raise InvalidValue("You can't add yourself; ask someone else in the Director's office.")
    already = f"{person.full_name} is already on this list."
    if await _membership(session, lst.id, person.id):
        raise InvalidValue(already)

    membership = AuthorisedSignatory(list_id=lst.id, user_id=person.id, added_by=actor.id)
    session.add(membership)
    try:
        await session.flush()  # sends the INSERT now, so membership.id exists for the audit row
    except IntegrityError:
        # Two admins adding the same person at the same moment: both passed the
        # check above, and the unique index authorised_signatories_current_key
        # stopped the second.
        await session.rollback()
        raise InvalidValue(already)
    record_event(
        session,
        actor=actor,
        action="signatory.added",
        entity_type=AUDIT_ENTITY,
        entity_id=membership.id,
        details={
            "list": lst.code,
            "user_id": person.id,
            # Names and posts as they were, for readers of the log.
            "name": person.full_name,
            "positions": sorted(person.position_codes),
        },
    )
    await session.commit()
    return membership


async def remove_signatory(session: AsyncSession, *, actor: User, membership_id: int) -> AuthorisedSignatory:
    """Take someone off a list, from now on. The row stays, with when and by whom."""
    _require_admin(actor)
    membership = await session.scalar(
        select(AuthorisedSignatory)
        .where(AuthorisedSignatory.id == membership_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if membership is None:
        raise NotFound("Signatory not found.")
    if membership.removed_at is not None:
        raise AlreadyRevoked("This person was already taken off the list.")
    lst = await session.get(SignatoryList, membership.list_id)
    person = await session.get(User, membership.user_id)

    membership.removed_at = func.now()
    membership.removed_by = actor.id
    record_event(
        session,
        actor=actor,
        action="signatory.removed",
        entity_type=AUDIT_ENTITY,
        entity_id=membership.id,
        details={"list": lst.code, "user_id": person.id, "name": person.full_name},
    )
    await session.commit()
    await session.refresh(membership, ["removed_at"])
    return membership
