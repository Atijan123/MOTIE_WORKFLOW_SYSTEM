"""Absence records: a post holder is away from one date to another.

The holder records their own absence, or someone with the absence_recorder role
records it for them; the audit log keeps who recorded it. The engine uses
absences to decide when the succession order applies (see succession.py).
"""

from datetime import date

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit.service import record_event
from app.core.identity.models import User
from app.core.workflow import delegation
from app.core.workflow.errors import AlreadyCancelled, InvalidAbsence, NotFound, NotPermitted
from app.core.workflow.models import Absence

AUDIT_ENTITY = "absence"

# [CONFIRM] Who may record an absence on someone else's behalf.
RECORDER_ROLE = "absence_recorder"


def _may_record_for_others(user: User) -> bool:
    return RECORDER_ROLE in user.role_codes


async def record_absence(
    session: AsyncSession,
    *,
    actor: User,
    absent_user_id: int,
    starts_on: date,
    ends_on: date,
    reason: str | None = None,
) -> Absence:
    on_behalf = absent_user_id != actor.id
    if on_behalf and not _may_record_for_others(actor):
        raise NotPermitted("You can only record your own absence.")

    absent = actor if not on_behalf else await session.get(User, absent_user_id)
    if absent is None or not absent.is_active:
        raise NotFound("User not found.")
    # Absence only matters for who may act for a post, so it needs a post.
    if not absent.positions:
        raise InvalidAbsence("Only someone who holds a position can be marked absent.")
    if starts_on > ends_on:
        raise InvalidAbsence("The absence ends before it starts.")
    # No back-dating, as for delegations: records show what was known at the time.
    if starts_on < delegation.today():
        raise InvalidAbsence("An absence can't start in the past.")

    absence = Absence(
        user_id=absent.id,
        starts_on=starts_on,
        ends_on=ends_on,
        reason=reason,
        recorded_by=actor.id,
    )
    session.add(absence)
    await session.flush()  # sends the INSERT now, so absence.id exists for the audit row
    record_event(
        session,
        actor=actor,
        action="absence.recorded",
        entity_type=AUDIT_ENTITY,
        entity_id=absence.id,
        details={
            "absent_user_id": absent.id,
            "recorded_by": actor.id,
            "on_behalf": on_behalf,
            # The posts they held when it was recorded, for readers of the log.
            "positions": sorted(absent.position_codes),
            "starts_on": starts_on.isoformat(),
            "ends_on": ends_on.isoformat(),
            "reason": reason,
        },
    )
    await session.commit()
    return absence


async def cancel_absence(session: AsyncSession, *, absence_id: int, actor: User) -> Absence:
    """End an absence now (they're back early). The absent person or a recorder may do it."""
    absence = await session.scalar(
        select(Absence)
        .where(Absence.id == absence_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if absence is None or not (absence.user_id == actor.id or _may_record_for_others(actor)):
        # Same answer for "doesn't exist" and "not yours" (see get_case()).
        raise NotFound("Absence not found.")
    if absence.cancelled_at is not None:
        raise AlreadyCancelled("This absence was already cancelled.")

    absence.cancelled_at = func.now()
    absence.cancelled_by = actor.id
    record_event(
        session,
        actor=actor,
        action="absence.cancelled",
        entity_type=AUDIT_ENTITY,
        entity_id=absence.id,
        details={"absent_user_id": absence.user_id},
    )
    await session.commit()
    await session.refresh(absence, ["cancelled_at"])
    return absence


async def list_absences(session: AsyncSession, user: User) -> list[Absence]:
    """Current and upcoming absences: your own, or everyone's for a recorder."""
    query = select(Absence).where(Absence.cancelled_at.is_(None), Absence.ends_on >= delegation.today())
    if not _may_record_for_others(user):
        query = query.where(or_(Absence.user_id == user.id, Absence.recorded_by == user.id))
    return list(await session.scalars(query.order_by(Absence.starts_on, Absence.id)))


async def absences_today(session: AsyncSession, user_ids: list[int]) -> dict[int, Absence]:
    """{user id: their absence covering today} for those of these users who are away."""
    if not user_ids:
        return {}
    on = delegation.today()
    result = await session.scalars(
        select(Absence)
        .where(
            Absence.user_id.in_(user_ids),
            Absence.cancelled_at.is_(None),
            Absence.starts_on <= on,
            Absence.ends_on >= on,
        )
        .order_by(Absence.id)
    )
    absences: dict[int, Absence] = {}
    for absence in result:
        absences.setdefault(absence.user_id, absence)
    return absences
