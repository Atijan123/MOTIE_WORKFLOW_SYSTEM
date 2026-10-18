from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit.models import AuditEvent
from app.core.identity.models import User


def record_event(
    session: AsyncSession,
    *,
    actor: User | None,
    action: str,
    entity_type: str,
    entity_id: int | str,
    details: dict[str, Any] | None = None,
) -> AuditEvent:
    """Add an audit row to the current transaction. Does NOT commit.

    Call it in the same transaction as the change it describes, and let the
    caller commit both together. Then a change can never be saved without its
    audit row, or an audit row without its change.
    """
    event = AuditEvent(
        actor_user_id=actor.id if actor else None,
        action=action,
        entity_type=entity_type,
        entity_id=str(entity_id),
        details=details or {},
    )
    session.add(event)
    return event


async def history(session: AsyncSession, entity_type: str, entity_id: int | str) -> list[AuditEvent]:
    """All events for one record, oldest first."""
    result = await session.scalars(
        select(AuditEvent)
        .where(AuditEvent.entity_type == entity_type, AuditEvent.entity_id == str(entity_id))
        .order_by(AuditEvent.occurred_at, AuditEvent.id)
    )
    return list(result)
