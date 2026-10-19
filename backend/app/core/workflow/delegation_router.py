from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.identity.deps import get_current_user
from app.core.identity.models import User
from app.core.workflow import delegation as delegations
from app.core.workflow.models import Delegation
from app.core.workflow.schemas import CreateDelegationRequest, DelegationOut
from app.db.session import get_session

# Errors are the engine's WorkflowError subclasses, so the handler registered in
# main.py turns them into HTTP statuses here too.
router = APIRouter(prefix="/delegations", tags=["delegations"])


def _out(d: Delegation) -> DelegationOut:
    return DelegationOut(
        id=d.id,
        from_position=d.from_position.code,
        to_position=d.to_position.code,
        workflow=d.workflow.code if d.workflow else None,
        starts_on=d.starts_on,
        ends_on=d.ends_on,
        reason=d.reason,
        created_by=d.created_by,
        created_at=d.created_at,
        revoked_at=d.revoked_at,
    )


@router.post("", response_model=DelegationOut, status_code=status.HTTP_201_CREATED)
async def create_delegation(
    body: CreateDelegationRequest,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    delegation = await delegations.create_delegation(
        session,
        actor=user,
        from_position_code=body.from_position,
        to_position_code=body.to_position,
        starts_on=body.starts_on,
        ends_on=body.ends_on,
        workflow_code=body.workflow,
        reason=body.reason,
    )
    return _out(delegation)


@router.get("", response_model=list[DelegationOut])
async def list_delegations(
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """Current and upcoming delegations given by, or to, your posts."""
    return [_out(d) for d in await delegations.list_delegations(session, user)]


@router.post("/{delegation_id}/revoke", response_model=DelegationOut)
async def revoke_delegation(
    delegation_id: int,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    delegation = await delegations.revoke_delegation(session, delegation_id=delegation_id, actor=user)
    return _out(delegation)
