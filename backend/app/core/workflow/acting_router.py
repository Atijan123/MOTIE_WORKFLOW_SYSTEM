from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.identity.deps import get_current_user
from app.core.identity.models import User
from app.core.workflow import acting
from app.core.workflow.schemas import ActingNowOut, CoverForPostOut
from app.db.session import get_session

router = APIRouter(prefix="/acting", tags=["absences"])


@router.get("", response_model=list[ActingNowOut])
async def acting_now(
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """The posts I'm acting for today (the banner on every screen). Empty when none."""
    return [ActingNowOut.model_validate(a, from_attributes=True) for a in await acting.acting_now(session, user)]


@router.get("/for-me", response_model=list[CoverForPostOut])
async def cover_for_me(
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """For each of my posts: my delegations, and who acts under the succession order if I'm away."""
    return [CoverForPostOut.model_validate(c, from_attributes=True) for c in await acting.cover_for_me(session, user)]
