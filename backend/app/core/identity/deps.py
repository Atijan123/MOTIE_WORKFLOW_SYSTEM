"""FastAPI dependencies for "who is calling?" and "are they allowed?"."""

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.identity.models import User
from app.core.identity.security import decode_access_token
from app.db.session import get_session

# Reads the "Authorization: Bearer <token>" header. auto_error=False lets us
# return our own 401 (with the right header) instead of FastAPI's default 403.
_bearer = HTTPBearer(auto_error=False)


def _unauthorized() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Not authenticated",
        headers={"WWW-Authenticate": "Bearer"},
    )


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    session: AsyncSession = Depends(get_session),
) -> User:
    if credentials is None:
        raise _unauthorized()
    try:
        user_id = decode_access_token(credentials.credentials)
    except jwt.InvalidTokenError:
        raise _unauthorized()

    # Look the user up on every request rather than trusting roles stored in the
    # token: deactivating someone or changing their roles takes effect at once.
    user = await session.get(User, user_id)
    if user is None or not user.is_active:
        raise _unauthorized()
    return user


def require_role(*role_codes: str):
    """Dependency factory: `Depends(require_role("admin"))` allows only those roles.

    The caller needs at least one of the listed roles. 401 = we don't know who
    you are; 403 = we know, and you're not allowed.
    """
    allowed = set(role_codes)

    async def checker(user: User = Depends(get_current_user)) -> User:
        if not user.role_codes & allowed:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not allowed")
        return user

    return checker
