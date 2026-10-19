"""Facts about a case that document conditions can test, supplied by modules.

The core can't read module tables, so each module registers a function that
returns plain facts for its workflow, e.g. {"product": "Portland cement"}:

    register("etls_facility_letter", facility_letter_facts)
"""

from collections.abc import Awaitable, Callable
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

FactsFunction = Callable[[AsyncSession, int], Awaitable[dict[str, Any]]]

_providers: dict[str, FactsFunction] = {}


def register(workflow_code: str, provider: FactsFunction) -> None:
    _providers[workflow_code] = provider


async def facts_for(session: AsyncSession, workflow_code: str, case_id: int) -> dict[str, Any]:
    provider = _providers.get(workflow_code)
    return await provider(session, case_id) if provider else {}
