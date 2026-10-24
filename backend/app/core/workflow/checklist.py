"""Recorded ticks: things an officer confirms by hand at a step, one tick each.

E.g. at the ETLS desk: "the exporter's approval is on the ECOWAS ETLS list".
The items are data (core.checklist_items, per workflow and step). Each tick
records who and when, and ticking and unticking are both audited, so the
history shows who said they had checked what.

- The check "checklist_complete" (on a move) needs every item of the case's
  current step to be ticked.
- The effect "clear_checklist" (on returns) removes a case's ticks: after the
  applicant changes their application, it's checked again from scratch.
"""

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit.service import record_event
from app.core.identity.models import User
from app.core.workflow import checks, effects
from app.core.workflow import service as workflow
from app.core.workflow.models import Case, CaseTick, ChecklistItem

CHECKLIST_COMPLETE = "checklist_complete"


@dataclass
class ItemStatus:
    item: ChecklistItem
    ticked_by: int | None
    ticked_at: datetime | None

    @property
    def ticked(self) -> bool:
        return self.ticked_at is not None


async def checklist(session: AsyncSession, case: Case) -> list[ItemStatus]:
    """Every item of the case's workflow, in order, with its tick if any."""
    items = await session.scalars(
        select(ChecklistItem)
        .where(ChecklistItem.workflow_id == case.workflow_id)
        .order_by(ChecklistItem.sort_order, ChecklistItem.id)
    )
    ticks = {t.item_id: t for t in await session.scalars(select(CaseTick).where(CaseTick.case_id == case.id))}
    return [
        ItemStatus(i, ticks[i.id].ticked_by if i.id in ticks else None, ticks[i.id].ticked_at if i.id in ticks else None)
        for i in items
    ]


async def set_tick(session: AsyncSession, *, case_id: int, code: str, actor: User, ticked: bool) -> ItemStatus:
    """Tick or untick one item. Allowed for whoever may make the move that
    needs the checklist (the desk's Verify, or someone acting for the desk),
    and only for items of the case's current step."""
    case = await workflow.get_case(session, case_id, actor, for_update=True)
    item = await session.scalar(
        select(ChecklistItem).where(ChecklistItem.workflow_id == case.workflow_id, ChecklistItem.code == code)
    )
    if item is None:
        raise workflow.NotFound(f"This kind of case has no checklist item '{code}'.")
    if item.status_id != case.current_status_id:
        raise workflow.TransitionNotAllowed("This item isn't ticked at the case's current step.")
    if not await workflow.may_make_move_with_check(session, case, actor, CHECKLIST_COMPLETE):
        raise workflow.NotPermitted("Only the officer at this step can tick its checks.")

    tick = await session.get(CaseTick, (case.id, item.id))
    if ticked and tick is None:
        session.add(CaseTick(case_id=case.id, item_id=item.id, ticked_by=actor.id))
    elif not ticked and tick is not None:
        await session.delete(tick)
    else:
        return ItemStatus(item, tick.ticked_by if tick else None, tick.ticked_at if tick else None)  # no change
    record_event(
        session,
        actor=actor,
        action="case.ticked" if ticked else "case.unticked",
        entity_type=workflow.AUDIT_ENTITY,
        entity_id=case.id,
        details={"item": item.code, "label": item.label},
    )
    await session.commit()
    [status] = [s for s in await checklist(session, case) if s.item.id == item.id]
    return status


async def _check_complete(session: AsyncSession, case: Case) -> list[str]:
    return [
        f"'{s.item.label}' isn't ticked"
        for s in await checklist(session, case)
        if s.item.status_id == case.current_status_id and not s.ticked
    ]


async def _clear(session: AsyncSession, move: effects.Move) -> None:
    """A returned case loses its ticks. The audit log keeps who had ticked what."""
    await session.execute(delete(CaseTick).where(CaseTick.case_id == move.case.id))


checks.register(CHECKLIST_COMPLETE, _check_complete)
effects.register("clear_checklist", _clear)
