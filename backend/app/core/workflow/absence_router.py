from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.identity.deps import get_current_user
from app.core.identity.models import User
from app.core.workflow import absence as absences
from app.core.workflow import acting, service
from app.core.workflow.models import Absence
from app.core.workflow.schemas import AbsenceOut, AbsenceViewOut, RecordAbsenceRequest
from app.db.session import get_session

# Errors are the engine's WorkflowError subclasses, so the handler registered in
# main.py turns them into HTTP statuses here too.
router = APIRouter(prefix="/absences", tags=["absences"])


def _out(a: Absence) -> AbsenceOut:
    return AbsenceOut(
        id=a.id,
        user_id=a.user_id,
        starts_on=a.starts_on,
        ends_on=a.ends_on,
        reason=a.reason,
        recorded_by=a.recorded_by,
        created_at=a.created_at,
        cancelled_at=a.cancelled_at,
    )


@router.post("", response_model=AbsenceOut, status_code=status.HTTP_201_CREATED)
async def record_absence(
    body: RecordAbsenceRequest,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    absence = await absences.record_absence(
        session,
        actor=user,
        absent_user_id=body.user_id if body.user_id is not None else user.id,
        starts_on=body.starts_on,
        ends_on=body.ends_on,
        reason=body.reason,
    )
    return _out(absence)


@router.get("", response_model=list[AbsenceOut])
async def list_absences(
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """Current and upcoming absences: your own (and ones you recorded), or all for a recorder."""
    return [_out(a) for a in await absences.list_absences(session, user)]


@router.get("/current", response_model=list[AbsenceViewOut])
async def current_absences(
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """Everyone away now or soon (S11), soonest first. Staff only."""
    if not service.is_staff(user):
        raise service.NotPermitted("Only Ministry staff can see who is away.")
    return [AbsenceViewOut.model_validate(a, from_attributes=True) for a in await acting.current_absences(session, user)]


@router.post("/{absence_id}/cancel", response_model=AbsenceOut)
async def cancel_absence(
    absence_id: int,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    return _out(await absences.cancel_absence(session, absence_id=absence_id, actor=user))
