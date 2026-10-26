from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.identity import password_links
from app.core.identity.deps import get_current_user
from app.core.identity.models import User
from app.core.identity.schemas import LoginRequest, SetPasswordRequest, TokenResponse, UserOut
from app.core.identity.security import create_access_token
from app.core.identity.service import WeakPassword, authenticate
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
        positions=[p.code for p in sorted(user.positions, key=lambda p: p.code)],
        position_titles=[p.title for p in sorted(user.positions, key=lambda p: p.code)],
    )


@router.post("/set-password", status_code=status.HTTP_204_NO_CONTENT)
async def set_password(body: SetPasswordRequest, session: AsyncSession = Depends(get_session)):
    """Set a password with the token from an emailed link, then log in as usual.
    No login needed: the token is the proof. Each link works once."""
    try:
        await password_links.set_password(session, token=body.token, password=body.password)
    except WeakPassword as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))
    except password_links.InvalidLink as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    return Response(status_code=status.HTTP_204_NO_CONTENT)
