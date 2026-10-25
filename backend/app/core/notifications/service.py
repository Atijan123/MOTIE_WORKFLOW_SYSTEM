"""Telling applicants what happened to their case, by email.

The engine calls notify_applicant() for every move, inside the move's
transaction (see change_status() in core/workflow/service.py). It writes an
email to the outbox (core.notifications) only when the move added a line to
the applicant's timeline. So the email says exactly what the timeline says:
the plain label, the status's explanation, and the message to the applicant
on a return or rejection. Never an internal minute, a staff name or a hidden
move (cancelling a letter). The worker sends it later.
"""

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit.models import AuditEvent
from app.core.identity.models import User
from app.core.notifications.models import Notification
from app.core.workflow.history import applicant_timeline
from app.core.workflow.models import Case, WorkflowStatus

# [CONFIRM] The wording, with the Ministry (and whether to send in French too).
SIGN_OFF = "Ministry of Trade, Industry, Regional Integration and Employment\nThe Gambia"


async def notify_applicant(session: AsyncSession, case: Case, event: AuditEvent) -> Notification | None:
    """Add the email for this move to the outbox, if the applicant sees the move. Does NOT commit."""
    entries = await applicant_timeline(session, case)  # also flushes `event`, giving it its id
    if not entries or entries[-1].event_id != event.id:
        return None  # hidden, or the same step again in other words (no news for the applicant)
    entry = entries[-1]
    applicant = await session.get(User, case.created_by)
    if applicant is None or not applicant.is_active:
        return None
    status = await session.get(WorkflowStatus, case.current_status_id)

    lines = [
        f"Dear {applicant.full_name},",
        "",
        f"Your application {case.reference} ({case.workflow.name}) is now: {entry.label}.",
    ]
    if status.applicant_explanation:
        lines.append(status.applicant_explanation)
    if entry.message:
        lines += ["", "Message from the Ministry:", entry.message]
    lines += ["", "Log in to the Ministry's online services to see your application.", "", SIGN_OFF]

    notification = Notification(
        user_id=applicant.id,
        to_email=applicant.email,
        subject=f"{case.reference}: {entry.label}",
        body="\n".join(lines),
        case_id=case.id,
        audit_event_id=event.id,
    )
    session.add(notification)
    return notification
