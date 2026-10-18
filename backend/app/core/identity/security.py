from datetime import datetime, timedelta, timezone

import jwt
from pwdlib import PasswordHash

from app.core.config import settings

# Argon2 with pwdlib's recommended settings. Argon2 is deliberately slow and
# memory-hungry, so someone who steals the users table can't cheaply guess passwords.
_hasher = PasswordHash.recommended()

# HS256: the token is signed with JWT_SECRET. Only our server knows the secret,
# so only our server can make a token that passes verification.
_ALGORITHM = "HS256"


def hash_password(plain: str) -> str:
    # The result includes a random salt, so two users with the same password
    # get different hashes.
    return _hasher.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    return _hasher.verify(plain, hashed)


def create_access_token(user_id: int) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),  # who the token is for
        "iat": now,  # issued at
        "exp": now + timedelta(minutes=settings.access_token_minutes),  # expires at
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=_ALGORITHM)


def decode_access_token(token: str) -> int:
    """Return the user id in a valid token; raise jwt.InvalidTokenError otherwise.

    Checks the signature and the expiry. `algorithms=[...]` is pinned so a forged
    token can't tell us to skip verification (the classic "alg: none" attack).
    """
    payload = jwt.decode(token, settings.jwt_secret, algorithms=[_ALGORITHM])
    return int(payload["sub"])
