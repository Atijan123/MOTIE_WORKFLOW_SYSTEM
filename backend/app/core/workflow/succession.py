"""Succession: which post acts when a post's holder is absent.

The order comes from core.succession_orders (loaded by migrations). Absences
(step 5c) decide who is away; the engine (service.py) puts the two together.
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.workflow.models import SuccessionStep


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
