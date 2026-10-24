"""A case's history, as staff and applicants see it.

- staff_history(): every audit row, newest first, with the actor's name and
  post title, and, when someone acted for another post, that post and the
  absences or delegation it relied on (with their dates).
- applicant_timeline(): only the status changes an applicant may see, as plain
  labels with dates. No names, no comments, no internal step names.

Both read core.audit_log; nothing here is stored twice.
"""

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit.models import AuditEvent
from app.core.audit.service import history
from app.core.identity.models import Position, User
from app.core.workflow import service
from app.core.workflow.models import Absence, Case, Delegation, WorkflowStatus, WorkflowTransition


@dataclass
class AbsenceSeen:
    person: str
    starts_on: date
    ends_on: date


@dataclass
class DelegationSeen:
    from_position: str  # titles, e.g. "Permanent Secretary"
    to_position: str
    starts_on: date
    ends_on: date


@dataclass
class ActingFor:
    position: str  # code, e.g. "permanent_secretary"
    title: str  # e.g. "Permanent Secretary"
    basis: str  # "delegation" or "succession"
    absences: list[AbsenceSeen] = field(default_factory=list)
    delegation: DelegationSeen | None = None


@dataclass
class HistoryEntry:
    occurred_at: datetime
    action: str
    actor_user_id: int | None
    actor_name: str | None
    actor_title: str | None  # the post they acted from, when the row records one
    acting_for: ActingFor | None
    details: dict[str, Any]


async def staff_history(session: AsyncSession, case: Case) -> list[HistoryEntry]:
    events = list(reversed(await history(session, service.AUDIT_ENTITY, case.id)))

    # Everything the rows point at, loaded in a few queries rather than per row.
    user_ids = {e.actor_user_id for e in events if e.actor_user_id}
    absence_ids = {a for e in events for a in e.details.get("absence_ids") or []}
    delegation_ids = {e.details["delegation_id"] for e in events if e.details.get("delegation_id")}
    absences = {a.id: a for a in await _load(session, Absence, absence_ids)}
    delegations = {d.id: d for d in await _load(session, Delegation, delegation_ids)}
    user_ids |= {a.user_id for a in absences.values()}
    names = {u.id: u.full_name for u in await _load(session, User, user_ids)}
    positions = list(await session.scalars(select(Position)))  # a few dozen rows
    titles = {p.code: p.title for p in positions}
    titles_by_id = {p.id: p.title for p in positions}

    entries = []
    for e in events:
        acting_for = None
        if e.details.get("on_behalf_of"):
            code = e.details["on_behalf_of"]
            delegation = delegations.get(e.details.get("delegation_id"))
            acting_for = ActingFor(
                position=code,
                title=titles.get(code, code),
                basis=e.details.get("basis") or ("delegation" if delegation else "succession"),
                absences=[
                    AbsenceSeen(names.get(a.user_id, "?"), a.starts_on, a.ends_on)
                    for a in (absences.get(i) for i in e.details.get("absence_ids") or [])
                    if a is not None
                ],
                delegation=DelegationSeen(
                    titles_by_id[delegation.from_position_id],
                    titles_by_id[delegation.to_position_id],
                    delegation.starts_on,
                    delegation.ends_on,
                )
                if delegation
                else None,
            )
        as_position = e.details.get("as_position")
        entries.append(
            HistoryEntry(
                occurred_at=e.occurred_at,
                action=e.action,
                actor_user_id=e.actor_user_id,
                actor_name=names.get(e.actor_user_id),
                actor_title=titles.get(as_position) if as_position else None,
                acting_for=acting_for,
                details=e.details,
            )
        )
    return entries


async def _load(session: AsyncSession, model, ids: set[int]) -> list:
    if not ids:
        return []
    return list(await session.scalars(select(model).where(model.id.in_(ids))))


@dataclass
class TimelineEntry:
    occurred_at: datetime
    label: str
    message: str | None = None  # the message to the applicant, on a return or rejection


async def current_message(session: AsyncSession, case: Case) -> str | None:
    """The message to the applicant on the move that put the case where it is
    now, e.g. why it was returned. None when that move sent none."""
    event = await session.scalar(
        select(AuditEvent)
        .where(
            AuditEvent.entity_type == service.AUDIT_ENTITY,
            AuditEvent.entity_id == str(case.id),
            AuditEvent.action == "case.status_changed",
        )
        .order_by(AuditEvent.occurred_at.desc(), AuditEvent.id.desc())
        .limit(1)
    )
    if event is None or event.details.get("to") != case.current_status.code:
        return None
    return event.details.get("applicant_message")


async def applicant_timeline(session: AsyncSession, case: Case) -> list[TimelineEntry]:
    """What happened, in the applicant's words, oldest first.

    Each status change shows its move's applicant wording (e.g. "Originals
    checked") or else the new status's label. Moves marked invisible (cancelling
    a signed letter) are left out, and a label repeating the one before it is
    shown once (e.g. several internal minutes that all read "Accepted by the
    Ministry").
    """
    statuses = {
        s.code: s
        for s in await session.scalars(select(WorkflowStatus).where(WorkflowStatus.workflow_id == case.workflow_id))
    }
    moves = list(
        await session.scalars(select(WorkflowTransition).where(WorkflowTransition.workflow_id == case.workflow_id))
    )
    by_code = {s.id: s.code for s in statuses.values()}

    def move_for(event: AuditEvent) -> WorkflowTransition | None:
        # The audit row names the move and its two statuses; match all three.
        return next(
            (
                m
                for m in moves
                if by_code.get(m.from_status_id) == event.details.get("from")
                and by_code.get(m.to_status_id) == event.details.get("to")
                and m.name == event.details.get("transition")
            ),
            None,
        )

    entries: list[TimelineEntry] = []
    for event in await history(session, service.AUDIT_ENTITY, case.id):
        if event.action == "case.created":
            label = statuses[event.details["status"]].applicant_label
        elif event.action == "case.status_changed":
            move = move_for(event)
            if move is not None and not move.applicant_visible:
                continue
            target = statuses.get(event.details["to"])
            if target is None:
                continue  # a status since removed from the workflow; nothing safe to show
            label = (move.applicant_event if move else None) or target.applicant_label
        else:
            continue  # uploads, flags, letters: not part of the applicant's timeline
        message = event.details.get("applicant_message")
        if entries and entries[-1].label == label and not message:
            continue
        entries.append(TimelineEntry(event.occurred_at, label, message))
    return entries
