"""Case flags: something about a case needs a named post's attention.

Any code (core or a module) may raise a flag. A blocking flag holds the case
at its post's step: while it's open, change_status() refuses that post's
moves (e.g. the desk's Verify), but earlier steps carry on (Records still
receives the originals). A holder of the flag's post resolves it with a
written reason, and both events are audited.
"""

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit.service import record_event
from app.core.identity.models import Position, User
from app.core.workflow.errors import AlreadyResolved, NotFound, NotPermitted
from app.core.workflow.models import CaseFlag

AUDIT_ENTITY = "case"  # flag events belong in the case's history


async def raise_flag(
    session: AsyncSession,
    *,
    case_id: int,
    code: str,
    message: str,
    for_position_code: str,
    details: dict[str, Any] | None = None,
    actor: User | None = None,
    blocking: bool = True,
) -> CaseFlag:
    """Add a flag and its audit row to the current transaction. Does NOT commit,
    so a flag is saved together with whatever caused it."""
    position = await session.scalar(select(Position).where(Position.code == for_position_code))
    flag = CaseFlag(
        case_id=case_id,
        code=code,
        message=message,
        details=details or {},
        for_position_id=position.id,
        blocking=blocking,
        raised_by=actor.id if actor else None,
    )
    session.add(flag)
    await session.flush()
    record_event(
        session,
        actor=actor,
        action="case.flag_raised",
        entity_type=AUDIT_ENTITY,
        entity_id=case_id,
        details={"flag_id": flag.id, "code": code, "for_position": for_position_code, **(details or {})},
    )
    return flag


async def open_flags(session: AsyncSession, case_id: int, *, blocking_only: bool = False) -> list[CaseFlag]:
    query = select(CaseFlag).where(CaseFlag.case_id == case_id, CaseFlag.resolved_at.is_(None))
    if blocking_only:
        query = query.where(CaseFlag.blocking)
    return list(await session.scalars(query.order_by(CaseFlag.id)))


async def case_flags(session: AsyncSession, case_id: int) -> list[CaseFlag]:
    """All flags on a case, open and resolved, oldest first."""
    return list(
        await session.scalars(select(CaseFlag).where(CaseFlag.case_id == case_id).order_by(CaseFlag.id))
    )


async def holding(session: AsyncSession, case_id: int, transition) -> list[CaseFlag]:
    """The open blocking flags that stop this move: those for the post whose move it is."""
    return [
        f
        for f in await open_flags(session, case_id, blocking_only=True)
        if f.for_position_id == transition.required_position_id
    ]


def resolve_by_move(session: AsyncSession, flag: CaseFlag, *, actor: User, move_name: str, reason: str) -> None:
    """Resolve an open flag as part of a move allowed on hold (e.g. rejecting
    a case held for a duplicate certificate). Does NOT commit: it's saved with
    the move. The move's own permission rules have already been applied."""
    flag.resolved_at = func.now()
    flag.resolved_by = actor.id
    flag.resolution = f"{move_name}: {reason}"
    record_event(
        session,
        actor=actor,
        action="case.flag_resolved",
        entity_type=AUDIT_ENTITY,
        entity_id=flag.case_id,
        details={"flag_id": flag.id, "code": flag.code, "resolution": flag.resolution, "by_move": move_name},
    )


async def resolve_flag(
    session: AsyncSession, *, case_id: int, flag_id: int, actor: User, resolution: str
) -> CaseFlag:
    flag = await session.scalar(
        select(CaseFlag)
        .where(CaseFlag.id == flag_id, CaseFlag.case_id == case_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if flag is None:
        raise NotFound("Flag not found.")
    # [CONFIRM] Only a holder of the post the flag is for. Delegation and
    # succession don't apply to flags yet.
    if flag.for_position_id not in {p.id for p in actor.positions}:
        raise NotPermitted(f"Only the {flag.for_position.title} can resolve this flag.")
    if flag.resolved_at is not None:
        raise AlreadyResolved("This flag was already resolved.")

    flag.resolved_at = func.now()
    flag.resolved_by = actor.id
    flag.resolution = resolution
    record_event(
        session,
        actor=actor,
        action="case.flag_resolved",
        entity_type=AUDIT_ENTITY,
        entity_id=case_id,
        details={"flag_id": flag.id, "code": flag.code, "resolution": resolution},
    )
    await session.commit()
    await session.refresh(flag, ["resolved_at"])
    return flag
