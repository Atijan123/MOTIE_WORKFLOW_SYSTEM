from fastapi import APIRouter, Depends, Request, status
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit.service import history
from app.core.identity.deps import get_current_user
from app.core.identity.models import User
from app.core.workflow import service
from app.core.workflow.models import Case
from app.core.workflow.schemas import (
    ActionOut,
    AuditEventOut,
    CaseOut,
    ChangeStatusRequest,
    StartCaseRequest,
    StatusOut,
)
from app.db.session import get_session

router = APIRouter(prefix="/cases", tags=["cases"])

_ERROR_STATUS = {
    service.NotFound: status.HTTP_404_NOT_FOUND,
    service.NotPermitted: status.HTTP_403_FORBIDDEN,
    service.TransitionNotAllowed: status.HTTP_409_CONFLICT,  # valid request, wrong moment
    service.AlreadyRevoked: status.HTTP_409_CONFLICT,
    service.AlreadyCancelled: status.HTTP_409_CONFLICT,
    service.InvalidDelegation: status.HTTP_422_UNPROCESSABLE_ENTITY,  # breaks a rule, don't retry
    service.InvalidAbsence: status.HTTP_422_UNPROCESSABLE_ENTITY,
}


async def workflow_error_handler(request: Request, exc: service.WorkflowError) -> JSONResponse:
    """Registered in main.py: turns engine errors into HTTP responses."""
    return JSONResponse(status_code=_ERROR_STATUS[type(exc)], content={"detail": str(exc)})


async def _case_out(session: AsyncSession, case: Case, user: User) -> CaseOut:
    moves = await service.available_transitions(session, case, user)
    return CaseOut(
        id=case.id,
        workflow=case.workflow.code,
        status=StatusOut(
            code=case.current_status.code,
            name=case.current_status.name,
            is_final=case.current_status.is_final,
        ),
        created_by=case.created_by,
        created_at=case.created_at,
        updated_at=case.updated_at,
        available_actions=[
            ActionOut(
                to_status=m.transition.to_status.code,
                name=m.transition.name,
                on_behalf_of=m.delegation.from_position.code if m.delegation else None,
            )
            for m in moves
        ],
    )


@router.post("", response_model=CaseOut, status_code=status.HTTP_201_CREATED)
async def start_case(
    body: StartCaseRequest,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    case = await service.start_case(session, workflow_code=body.workflow, actor=user)
    return await _case_out(session, case, user)


@router.get("/{case_id}", response_model=CaseOut)
async def get_case(
    case_id: int,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    case = await service.get_case(session, case_id, user)
    return await _case_out(session, case, user)


@router.post("/{case_id}/status", response_model=CaseOut)
async def change_status(
    case_id: int,
    body: ChangeStatusRequest,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    case = await service.change_status(
        session, case_id=case_id, to_status_code=body.to_status, actor=user, comment=body.comment
    )
    return await _case_out(session, case, user)


@router.get("/{case_id}/history", response_model=list[AuditEventOut])
async def case_history(
    case_id: int,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    case = await service.get_case(session, case_id, user)
    # [CONFIRM] Placeholder: only staff see the history, because it holds
    # internal comments (minutes). Applicants see the current status only.
    if not service.is_staff(user):
        raise service.NotPermitted("Only Ministry staff can see a case's history.")
    events = await history(session, service.AUDIT_ENTITY, case.id)
    return [
        AuditEventOut(
            occurred_at=e.occurred_at,
            actor_user_id=e.actor_user_id,
            action=e.action,
            details=e.details,
        )
        for e in events
    ]
