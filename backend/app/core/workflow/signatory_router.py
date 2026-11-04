from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.identity.deps import get_current_user
from app.core.identity.models import User
from app.core.workflow import signatories
from app.core.workflow.models import AuthorisedSignatory
from app.core.workflow.schemas import (
    AddSignatoryRequest,
    SignatoryCandidateOut,
    SignatoryListOut,
    SignatoryOut,
)
from app.db.session import get_session

# S12. Every endpoint is for the signatory_admin role; signatories.py checks it,
# so the rule holds from the CLI and tests too. Its errors (WorkflowError) become
# HTTP statuses through the handler registered in main.py.
router = APIRouter(prefix="/signatories", tags=["signatories"])


async def _member_out(session: AsyncSession, actor: User, membership: AuthorisedSignatory) -> SignatoryOut:
    # Read back through the overview, so a new or removed entry looks exactly
    # as it will on the screen (names, posts, who added it).
    for lst in await signatories.overview(session, actor):
        for m in lst.current + lst.past:
            if m.id == membership.id:
                return SignatoryOut.model_validate(m, from_attributes=True)
    raise AssertionError("an entry that was just saved is missing")


@router.get("", response_model=list[SignatoryListOut])
async def list_signatories(
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """Every signatories list: where it applies, who is on it, who was."""
    return [SignatoryListOut.model_validate(v, from_attributes=True) for v in await signatories.overview(session, user)]


@router.get("/candidates", response_model=list[SignatoryCandidateOut])
async def candidates(
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """Staff who may be added to a list."""
    return [SignatoryCandidateOut.model_validate(c, from_attributes=True) for c in await signatories.candidates(session, user)]


@router.post("/{list_code}/members", response_model=SignatoryOut, status_code=status.HTTP_201_CREATED)
async def add_signatory(
    list_code: str,
    body: AddSignatoryRequest,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    membership = await signatories.add_signatory(session, actor=user, list_code=list_code, user_id=body.user_id)
    return await _member_out(session, user, membership)


@router.post("/members/{membership_id}/remove", response_model=SignatoryOut)
async def remove_signatory(
    membership_id: int,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    membership = await signatories.remove_signatory(session, actor=user, membership_id=membership_id)
    return await _member_out(session, user, membership)
