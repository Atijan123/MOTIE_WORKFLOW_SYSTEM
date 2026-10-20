from fastapi import APIRouter, Depends, Request, status
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit.service import history
from app.core.identity.deps import get_current_user
from app.core.identity.models import User
from app.core.workflow import flags, queues, service
from app.core.workflow.models import Case
from app.core.workflow.schemas import (
    ActionOut,
    AuditEventOut,
    CaseOut,
    CaseSummaryOut,
    ChangeStatusRequest,
    FlagOut,
    ResolveFlagRequest,
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
    service.AlreadyResolved: status.HTTP_409_CONFLICT,
    service.CaseBlocked: status.HTTP_409_CONFLICT,  # valid move, but the case is on hold
    service.NotReady: status.HTTP_409_CONFLICT,  # valid move, but e.g. a document is missing
    service.InvalidDelegation: status.HTTP_422_UNPROCESSABLE_ENTITY,  # breaks a rule, don't retry
    service.InvalidAbsence: status.HTTP_422_UNPROCESSABLE_ENTITY,
    service.InvalidDocument: status.HTTP_422_UNPROCESSABLE_ENTITY,
    service.CommentRequired: status.HTTP_422_UNPROCESSABLE_ENTITY,
    service.UploadTooLarge: status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
    service.UnsupportedFileType: status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
}


async def workflow_error_handler(request: Request, exc: service.WorkflowError) -> JSONResponse:
    """Registered in main.py: turns engine errors into HTTP responses."""
    return JSONResponse(status_code=_ERROR_STATUS[type(exc)], content={"detail": str(exc)})


def _action_out(m: service.PermittedMove) -> ActionOut:
    return ActionOut(
        to_status=m.transition.to_status.code,
        name=m.transition.name,
        on_behalf_of=m.on_behalf_of,
        requires_comment=m.transition.requires_comment,
    )


def _summary_out(item: queues.QueueItem, user: User) -> CaseSummaryOut:
    case = item.case
    return CaseSummaryOut(
        id=case.id,
        reference=case.reference,
        workflow=case.workflow.code,
        service=case.workflow.name,
        status=StatusOut(**service.status_view(case.current_status, user)),
        submitted_at=case.submitted_at,
        status_since=case.status_changed_at,
        days_waiting=item.days_waiting,
        summary=item.summary,
        applicant_name=item.applicant_name,
        available_actions=[_action_out(m) for m in item.moves],
    )


async def _case_out(session: AsyncSession, case: Case, user: User) -> CaseOut:
    moves = await service.available_transitions(session, case, user)
    return CaseOut(
        id=case.id,
        reference=case.reference,
        submitted_at=case.submitted_at,
        workflow=case.workflow.code,
        status=StatusOut(**service.status_view(case.current_status, user)),
        created_by=case.created_by,
        created_at=case.created_at,
        updated_at=case.updated_at,
        available_actions=[_action_out(m) for m in moves],
        on_hold=bool(await flags.open_flags(session, case.id, blocking_only=True))
        if service.is_staff(user)
        else None,
    )


@router.post("", response_model=CaseOut, status_code=status.HTTP_201_CREATED)
async def start_case(
    body: StartCaseRequest,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    case = await service.start_case(session, workflow_code=body.workflow, actor=user)
    return await _case_out(session, case, user)


# These two come before "/{case_id}", or FastAPI would try to read "queue" as a case id.
@router.get("", response_model=list[CaseSummaryOut])
async def my_cases(
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """The cases I applied for, newest first (the applicant's "my applications")."""
    return [_summary_out(item, user) for item in await queues.my_cases(session, user)]


@router.get("/queue", response_model=list[CaseSummaryOut])
async def my_queue(
    status: str | None = None,
    workflow: str | None = None,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """Open cases where I can make a move now (own post, delegation or succession),
    longest-waiting first. `?status=signed` narrows it, e.g. to Records' outgoing letters."""
    items = await queues.queue(session, user, status=status, workflow=workflow)
    return [_summary_out(item, user) for item in items]


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


def _flag_out(f) -> FlagOut:
    return FlagOut(
        id=f.id,
        code=f.code,
        message=f.message,
        details=f.details,
        for_position=f.for_position.code,
        blocking=f.blocking,
        raised_at=f.raised_at,
        resolved_at=f.resolved_at,
        resolved_by=f.resolved_by,
        resolution=f.resolution,
    )


@router.get("/{case_id}/flags", response_model=list[FlagOut])
async def case_flags(
    case_id: int,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    case = await service.get_case(session, case_id, user)
    if not service.is_staff(user):
        raise service.NotPermitted("Only Ministry staff can see a case's flags.")
    return [_flag_out(f) for f in await flags.case_flags(session, case.id)]


@router.post("/{case_id}/flags/{flag_id}/resolve", response_model=FlagOut)
async def resolve_flag(
    case_id: int,
    flag_id: int,
    body: ResolveFlagRequest,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    case = await service.get_case(session, case_id, user)
    flag = await flags.resolve_flag(
        session, case_id=case.id, flag_id=flag_id, actor=user, resolution=body.resolution
    )
    return _flag_out(flag)
