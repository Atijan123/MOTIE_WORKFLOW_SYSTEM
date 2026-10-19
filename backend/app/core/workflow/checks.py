"""Named checks that a transition can require before a case may move.

Which transition needs which check is data (core.transition_checks). What a
check does is a function registered here under its name, by whichever part of
the code knows how (e.g. the documents service registers "documents_complete").
A check returns the problems it found; an empty list means it passed.
"""

import logging
from collections.abc import Awaitable, Callable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.workflow.models import Case, TransitionCheck

logger = logging.getLogger(__name__)

CheckFunction = Callable[[AsyncSession, Case], Awaitable[list[str]]]

_checks: dict[str, CheckFunction] = {}


def register(code: str, check: CheckFunction) -> None:
    _checks[code] = check


def registered() -> set[str]:
    return set(_checks)


async def problems(session: AsyncSession, case: Case, transition_id: int) -> list[str]:
    """Everything that stops this move right now, from all its checks."""
    codes = await session.scalars(
        select(TransitionCheck.check_code)
        .where(TransitionCheck.transition_id == transition_id)
        .order_by(TransitionCheck.check_code)
    )
    found: list[str] = []
    for code in codes:
        check = _checks.get(code)
        if check is None:
            # A check named in the database with no code behind it is a set-up
            # mistake. Fail closed: refuse the move rather than skip the check.
            logger.error("Transition %s needs unknown check %r", transition_id, code)
            found.append(f"The check '{code}' isn't available; ask the system administrator.")
        else:
            found += await check(session, case)
    return found
