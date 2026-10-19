from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.identity.deps import get_current_user
from app.core.identity.models import User
from app.core.identity.schemas import LoginRequest, TokenResponse, UserOut
from app.core.identity.security import create_access_token
from app.core.identity.service import authenticate
from app.db.session import get_session

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=TokenResponse)
async def login(body: LoginRequest, session: AsyncSession = Depends(get_session)):
    user = await authenticate(session, body.email, body.password)
    if user is None:
        # One message for every failure (unknown email, wrong password,
        # deactivated account), so it reveals nothing.
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Incorrect email or password"
        )
    return TokenResponse(
        access_token=create_access_token(user.id),
        expires_in=settings.access_token_minutes * 60,
    )


@router.get("/me", response_model=UserOut)
async def me(user: User = Depends(get_current_user)):
    return UserOut(
        id=user.id,
        email=user.email,
        full_name=user.full_name,
        roles=sorted(user.role_codes),
        positions=sorted(user.position_codes),
    )
