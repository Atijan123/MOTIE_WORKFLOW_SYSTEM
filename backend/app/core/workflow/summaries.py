"""One-line summaries of cases ("goods") for lists and queues, supplied by modules.

The core can't read module tables, so each module registers a function that
returns a short text per case, e.g. {42: "Roofing sheets, 1200.5 tonnes"}:

    register("etls_facility_letter", facility_letter_summaries)

It takes many case ids at once, so a queue of 50 cases costs one query per
module, not 50.
"""

from collections.abc import Awaitable, Callable

from sqlalchemy.ext.asyncio import AsyncSession

SummaryFunction = Callable[[AsyncSession, list[int]], Awaitable[dict[int, str]]]

_providers: dict[str, SummaryFunction] = {}


def register(workflow_code: str, provider: SummaryFunction) -> None:
    _providers[workflow_code] = provider


async def summaries_for(session: AsyncSession, cases_by_workflow: dict[str, list[int]]) -> dict[int, str]:
    found: dict[int, str] = {}
    for workflow_code, case_ids in cases_by_workflow.items():
        provider = _providers.get(workflow_code)
        if provider and case_ids:
            found.update(await provider(session, case_ids))
    return found
