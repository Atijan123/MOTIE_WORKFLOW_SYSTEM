"""Succession: which post acts when a post's holder is absent.

The order comes from core.succession_orders (loaded by migrations). Absences
(step 5c) decide who is away; the engine (service.py) puts the two together.
"""

from typing import NamedTuple

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.identity.models import position_holders
from app.core.workflow.absence import absences_today
from app.core.workflow.models import Absence, SuccessionStep


async def succession_order(session: AsyncSession, position_id: int, workflow_id: int) -> list[int]:
    """The posts next in line for this post on this workflow, first one first.

    If the post has rows for this workflow, they replace its general rows: the
    ETLS order for the Director is the whole answer for ETLS, not an addition.
    """
    rows = (
        await session.scalars(
            select(SuccessionStep)
            .where(
                SuccessionStep.position_id == position_id,
                (SuccessionStep.workflow_id == workflow_id) | SuccessionStep.workflow_id.is_(None),
            )
            .order_by(SuccessionStep.rank)
        )
    ).all()
    specific = [r.successor_position_id for r in rows if r.workflow_id is not None]
    return specific or [r.successor_position_id for r in rows if r.workflow_id is None]


class Succession(NamedTuple):
    """The post next in line that is present, and the absences that put it there."""

    acting_position_id: int
    # The required post's holders' absences, plus those of any successor skipped
    # because they were away too. Recorded in the audit row.
    absences: list[Absence]


async def presence(session: AsyncSession, position_id: int) -> tuple[bool, list[Absence]]:
    """(is any holder of this post at work today?, absences of the holders who aren't)."""
    holder_ids = list(
        await session.scalars(
            select(position_holders.c.user_id).where(position_holders.c.position_id == position_id)
        )
    )
    away = await absences_today(session, holder_ids)
    return len(away) < len(holder_ids), list(away.values())


async def acting_successor(
    session: AsyncSession, position_id: int, workflow_id: int
) -> Succession | None:
    """Who acts for this post today because its holders are away, if anyone.

    Only applies when the post has holders and every one of them has an absence
    covering today. [CONFIRM] A vacant post (no holder at all) doesn't count as
    absent, so nobody acts for it until an absence is recorded or someone is
    appointed. Then the first post in the succession order with a holder at work
    acts; posts whose holders are all away (or that are vacant) are skipped.
    """
    present, away = await presence(session, position_id)
    if present or not away:
        return None
    reasons = list(away)
    for successor_id in await succession_order(session, position_id, workflow_id):
        present, away = await presence(session, successor_id)
        if present:
            return Succession(successor_id, reasons)
        reasons += away
    return None
