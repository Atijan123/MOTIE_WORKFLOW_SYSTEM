"""Delegation: a post's holder lets another post act for it, for a date range.

Delegations go from post to post, not person to person: if the PS changes while
the Minister is away, the new PS can act at once. The delegating post keeps its
own powers; delegation adds a second pair of hands, it doesn't take any away.

The engine (service.py) calls active_delegations_to() when a user tries a move
that none of their own posts allows.
"""

from datetime import date, datetime, timezone

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit.service import record_event
from app.core.identity.models import Position, User
from app.core.workflow.errors import AlreadyRevoked, InvalidDelegation, NotFound, NotPermitted
from app.core.workflow.models import Delegation, Workflow

AUDIT_ENTITY = "delegation"

# [CONFIRM] Placeholder. Open-ended delegation would quietly hand a post's
# powers to someone else for good, so each one must have an end date within this.
MAX_DELEGATION_DAYS = 90


def today() -> date:
    """The Ministry's date. The Gambia keeps GMT (UTC+0) all year with no
    daylight saving, so the UTC date is the local date.

    Tests replace this function to check delegations on other days.
    """
    return datetime.now(timezone.utc).date()


async def _position(session: AsyncSession, code: str) -> Position:
    position = await session.scalar(select(Position).where(Position.code == code))
    if position is None:
        raise NotFound(f"No position called '{code}'.")
    return position


async def create_delegation(
    session: AsyncSession,
    *,
    actor: User,
    from_position_code: str,
    to_position_code: str,
    starts_on: date,
    ends_on: date,
    workflow_code: str | None = None,
    reason: str | None = None,
) -> Delegation:
    from_position = await _position(session, from_position_code)
    to_position = await _position(session, to_position_code)

    # [CONFIRM] Only a holder of the post may delegate it. The Ministry may want
    # e.g. the Minister's private secretary to record it for them.
    if from_position.id not in {p.id for p in actor.positions}:
        raise NotPermitted("Only a holder of a position can delegate it.")
    if from_position.id == to_position.id:
        raise InvalidDelegation("A position can't delegate to itself.")
    if starts_on > ends_on:
        raise InvalidDelegation("The delegation ends before it starts.")
    # No back-dating: a delegation must not make an earlier action look authorised.
    if starts_on < today():
        raise InvalidDelegation("A delegation can't start in the past.")
    if (ends_on - starts_on).days + 1 > MAX_DELEGATION_DAYS:
        raise InvalidDelegation(f"A delegation can last at most {MAX_DELEGATION_DAYS} days.")

    workflow = None
    if workflow_code is not None:
        workflow = await session.scalar(select(Workflow).where(Workflow.code == workflow_code))
        if workflow is None:
            raise NotFound(f"No workflow called '{workflow_code}'.")

    delegation = Delegation(
        from_position_id=from_position.id,
        to_position_id=to_position.id,
        workflow_id=workflow.id if workflow else None,
        starts_on=starts_on,
        ends_on=ends_on,
        reason=reason,
        created_by=actor.id,
    )
    session.add(delegation)
    await session.flush()  # sends the INSERT now, so delegation.id exists for the audit row
    record_event(
        session,
        actor=actor,
        action="delegation.created",
        entity_type=AUDIT_ENTITY,
        entity_id=delegation.id,
        details={
            "from_position": from_position.code,
            "to_position": to_position.code,
            "workflow": workflow.code if workflow else None,
            "starts_on": starts_on.isoformat(),
            "ends_on": ends_on.isoformat(),
            "reason": reason,
        },
    )
    await session.commit()
    await session.refresh(delegation, ["from_position", "to_position", "workflow"])
    return delegation


async def revoke_delegation(session: AsyncSession, *, delegation_id: int, actor: User) -> Delegation:
    """End a delegation now. Only a holder of the delegating post may do it."""
    held = {p.id for p in actor.positions}
    delegation = await session.scalar(
        select(Delegation)
        .where(Delegation.id == delegation_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    involved = delegation is not None and (
        delegation.from_position_id in held or delegation.to_position_id in held
    )
    if not involved:
        # Same answer for "doesn't exist" and "not yours" (see get_case()).
        raise NotFound("Delegation not found.")
    if delegation.from_position_id not in held:
        raise NotPermitted("Only the delegating position can revoke a delegation.")
    if delegation.revoked_at is not None:
        raise AlreadyRevoked("This delegation was already revoked.")

    delegation.revoked_at = func.now()
    delegation.revoked_by = actor.id
    record_event(
        session,
        actor=actor,
        action="delegation.revoked",
        entity_type=AUDIT_ENTITY,
        entity_id=delegation.id,
    )
    await session.commit()
    await session.refresh(delegation, ["revoked_at"])
    return delegation


async def list_delegations(session: AsyncSession, user: User) -> list[Delegation]:
    """Current and upcoming delegations given by, or to, a post this user holds."""
    held = [p.id for p in user.positions]
    result = await session.scalars(
        select(Delegation)
        .where(
            or_(Delegation.from_position_id.in_(held), Delegation.to_position_id.in_(held)),
            Delegation.revoked_at.is_(None),
            Delegation.ends_on >= today(),
        )
        .order_by(Delegation.starts_on, Delegation.id)
    )
    return list(result)


async def active_delegations_to(
    session: AsyncSession, user: User, workflow_id: int
) -> dict[int, Delegation]:
    """Posts this user may act for today, on cases of this workflow.

    Returns {delegating position id: delegation}. Only direct delegations count:
    if the Minister delegates to the PS and the PS delegates to a Director, the
    Director may act for the PS but not for the Minister.
    """
    held = [p.id for p in user.positions]
    if not held:
        return {}
    on = today()
    result = await session.scalars(
        select(Delegation)
        .where(
            Delegation.to_position_id.in_(held),
            Delegation.revoked_at.is_(None),
            Delegation.starts_on <= on,
            Delegation.ends_on >= on,
            or_(Delegation.workflow_id.is_(None), Delegation.workflow_id == workflow_id),
        )
        .order_by(Delegation.id)
    )
    # If several delegations cover the same post, the oldest one is recorded.
    delegations: dict[int, Delegation] = {}
    for delegation in result:
        delegations.setdefault(delegation.from_position_id, delegation)
    return delegations


async def is_delegated_away(session: AsyncSession, position_id: int, workflow_id: int) -> bool:
    """Has this post delegated itself, today, for this workflow, to anyone?

    Used to give personal delegations priority over succession: if the Minister
    chose who acts while they're away, the standing order doesn't apply.
    """
    on = today()
    found = await session.scalar(
        select(Delegation.id)
        .where(
            Delegation.from_position_id == position_id,
            Delegation.revoked_at.is_(None),
            Delegation.starts_on <= on,
            Delegation.ends_on >= on,
            or_(Delegation.workflow_id.is_(None), Delegation.workflow_id == workflow_id),
        )
        .limit(1)
    )
    return found is not None
