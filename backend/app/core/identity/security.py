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


def create_access_token(user_id: int, session_id: str, expires_at: datetime) -> str:
    """The login token: who (`sub`), which session on the server (`sid`,
    step 12f; identity/sessions.py), and when it ends (that session's end)."""
    payload = {
        "sub": str(user_id),  # who the token is for
        "sid": session_id,  # their row in core.sessions
        "typ": "access",  # what it is for (see create_challenge_token)
        "iat": datetime.now(timezone.utc),  # issued at
        "exp": expires_at,  # expires at
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=_ALGORITHM)


def decode_access_token(token: str) -> tuple[int, str]:
    """(user id, session id) from a valid token; raise jwt.InvalidTokenError otherwise.

    Checks the signature and the expiry. `algorithms=[...]` is pinned so a forged
    token can't tell us to skip verification (the classic "alg: none" attack).
    Only "access" tokens with a session count: a challenge token (password
    right, code not yet given) must never work as a login.
    """
    payload = jwt.decode(token, settings.jwt_secret, algorithms=[_ALGORITHM])
    if payload.get("typ") != "access" or not isinstance(payload.get("sid"), str):
        raise jwt.InvalidTokenError("not an access token")
    return int(payload["sub"]), payload["sid"]


def create_challenge_token(user_id: int, portal: str) -> str:
    """Proof that this person got their password right a moment ago (step 12e).
    It allows exactly one thing: giving the second step (a code, a recovery
    code, or setting up an authenticator), for a few minutes, through the same app."""
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),
        "typ": "mfa_challenge",
        "portal": portal,
        "iat": now,
        "exp": now + timedelta(minutes=settings.mfa_challenge_minutes),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=_ALGORITHM)


def decode_challenge_token(token: str, portal: str | None) -> int:
    payload = jwt.decode(token, settings.jwt_secret, algorithms=[_ALGORITHM])
    if payload.get("typ") != "mfa_challenge" or payload.get("portal") != portal:
        raise jwt.InvalidTokenError("not a challenge for this app")
    return int(payload["sub"])
