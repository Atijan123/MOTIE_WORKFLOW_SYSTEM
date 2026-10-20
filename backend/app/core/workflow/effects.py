"""Named effects that a transition sets off, in the same transaction as the move.

The twin of checks.py: a check runs *before* a move and can stop it; an effect
runs *after* the status change and its audit row are added, before the commit.
Which transition sets off which effect is data (core.transition_effects). What
an effect does is a function registered here under its name, by the code that
knows how (e.g. the ETLS module registers "issue_facility_letter").

The move and everything an effect saves to the database succeed or fail
together. An effect that also writes outside the database (a file) returns a
function that undoes that write; the engine calls it if the commit fails.
"""

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit.models import AuditEvent
from app.core.identity.models import User
from app.core.workflow.errors import NotReady
from app.core.workflow.models import Case, TransitionEffect

logger = logging.getLogger(__name__)


@dataclass
class Move:
    case: Case
    actor: User
    # The move's audit row: who, from which post, acting for whom, and when.
    event: AuditEvent


Undo = Callable[[], None]
EffectFunction = Callable[[AsyncSession, Move], Awaitable[Undo | None]]

_effects: dict[str, EffectFunction] = {}


def register(code: str, effect: EffectFunction) -> None:
    _effects[code] = effect


def registered() -> set[str]:
    return set(_effects)


def undo_all(undos: list[Undo]) -> None:
    for undo in reversed(undos):
        try:
            undo()
        except Exception:  # keep undoing the rest; the original error matters more
            logger.exception("Undoing an effect failed")


async def run(session: AsyncSession, move: Move, transition_id: int) -> list[Undo]:
    """Run every effect of this transition. Returns what to undo if the commit fails."""
    codes = list(
        await session.scalars(
            select(TransitionEffect.effect_code)
            .where(TransitionEffect.transition_id == transition_id)
            .order_by(TransitionEffect.effect_code)
        )
    )
    missing = [code for code in codes if code not in _effects]
    if missing:
        # An effect named in the database with no code behind it is a set-up
        # mistake. Fail closed: refuse the move rather than skip, say, issuing
        # the letter the move is supposed to produce.
        logger.error("Transition %s needs unknown effect(s) %r", transition_id, missing)
        raise NotReady(f"The step '{missing[0]}' isn't available; ask the system administrator.")

    undos: list[Undo] = []
    try:
        for code in codes:
            if undo := await _effects[code](session, move):
                undos.append(undo)
    except BaseException:
        undo_all(undos)
        raise
    return undos
