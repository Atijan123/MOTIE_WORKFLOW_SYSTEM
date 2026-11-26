"""Two-step login for staff (step 12e): an authenticator app, plus one-time
recovery codes for when the phone is lost.

Signing in as staff is: password (router.login) -> a short-lived challenge
token -> one of
  - a 6-digit code from their authenticator app   (verify_code)
  - a recovery code                                (use_recovery_code)
  - the first time: setting the app up             (start_enrolment, confirm_enrolment)
-> a real session.

The authenticator secret is stored encrypted with MFA_SECRET_KEY. Recovery
codes are stored as SHA-256 hashes only and shown once, when made.
"""

import base64
import hashlib
import secrets
from datetime import datetime, timezone
from io import BytesIO

import qrcode
import qrcode.image.svg
from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit.service import record_event
from app.core.config import settings
from app.core.identity import totp
from app.core.identity.models import RecoveryCode, TotpCredential, User

ISSUER = "MOTIE ETLS"
RECOVERY_CODE_COUNT = 10
# No 0/O, 1/I/L: people copy these from paper.
_RECOVERY_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
AUDIT_ENTITY = "user"


class TwoStepUnavailable(Exception):
    """MFA_SECRET_KEY isn't set: staff can't sign in until it is."""


class AlreadyEnrolled(Exception):
    pass


def _fernet() -> Fernet:
    key = settings.mfa_key()
    if not key:
        raise TwoStepUnavailable("Two-step login isn't set up on this server (MFA_SECRET_KEY).")
    # Fernet wants exactly 32 bytes, base64-encoded; any long setting will do.
    return Fernet(base64.urlsafe_b64encode(hashlib.sha256(key.encode()).digest()))


def ensure_available() -> None:
    """Raise TwoStepUnavailable now, with a clear message, if MFA_SECRET_KEY isn't set."""
    _fernet()


def _encrypt(secret: str) -> str:
    return _fernet().encrypt(secret.encode()).decode()


def _decrypt(token: str) -> str:
    try:
        return _fernet().decrypt(token.encode()).decode()
    except InvalidToken:
        # Wrong MFA_SECRET_KEY (it was changed): nobody's codes can be checked.
        raise TwoStepUnavailable("The authenticator secrets can't be read with this MFA_SECRET_KEY.")


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def _credential(session: AsyncSession, user: User) -> TotpCredential | None:
    return await session.get(TotpCredential, user.id, populate_existing=True)


async def is_enrolled(session: AsyncSession, user: User) -> bool:
    credential = await _credential(session, user)
    return credential is not None and credential.confirmed_at is not None


def qr_svg(uri: str) -> str:
    """The setup link as an SVG QR code, for the page to show."""
    image = qrcode.make(uri, image_factory=qrcode.image.svg.SvgPathImage, box_size=8, border=2)
    out = BytesIO()
    image.save(out)
    return out.getvalue().decode()


async def start_enrolment(session: AsyncSession, user: User) -> tuple[str, str]:
    """A new secret for `user` to scan; returns (secret, otpauth link). Asking
    again before confirming replaces the secret (e.g. the page was reloaded)."""
    if await is_enrolled(session, user):
        raise AlreadyEnrolled("An authenticator is already set up for this account.")
    secret = totp.new_secret()
    credential = await _credential(session, user)
    if credential is None:
        session.add(TotpCredential(user_id=user.id, secret_encrypted=_encrypt(secret)))
    else:
        credential.secret_encrypted = _encrypt(secret)
        credential.created_at = _now()
    await session.commit()
    return secret, totp.provisioning_uri(secret, account=user.email or str(user.id), issuer=ISSUER)


async def confirm_enrolment(session: AsyncSession, user: User, code: str) -> list[str] | None:
    """Finish setting up: `code` must come from the new secret. Returns the
    recovery codes (shown once), or None if the code is wrong."""
    credential = await _credential(session, user)
    if credential is None or credential.confirmed_at is not None:
        return None
    step = totp.matching_step(_decrypt(credential.secret_encrypted), code)
    if step is None:
        return None
    credential.confirmed_at = _now()
    credential.last_used_step = step
    codes = await _replace_recovery_codes(session, user)
    record_event(session, actor=user, action="auth.two_step_set_up", entity_type=AUDIT_ENTITY, entity_id=user.id)
    await session.commit()
    return codes


async def verify_code(session: AsyncSession, user: User, code: str) -> bool:
    credential = await _credential(session, user)
    if credential is None or credential.confirmed_at is None:
        return False
    step = totp.matching_step(_decrypt(credential.secret_encrypted), code, after_step=credential.last_used_step)
    if step is None:
        return False
    # Only if no one used this step (or a later one) a moment ago: two logins
    # racing with the same code can't both succeed.
    used = await session.scalar(
        update(TotpCredential)
        .where(
            TotpCredential.user_id == user.id,
            (TotpCredential.last_used_step.is_(None)) | (TotpCredential.last_used_step < step),
        )
        .values(last_used_step=step)
        .returning(TotpCredential.user_id)
    )
    await session.commit()
    return used is not None


def _normalise_recovery_code(code: str) -> str:
    return "".join(ch for ch in code.upper() if ch.isalnum())


def _hash(code: str) -> str:
    return hashlib.sha256(_normalise_recovery_code(code).encode()).hexdigest()


def _new_recovery_code() -> str:
    raw = "".join(secrets.choice(_RECOVERY_ALPHABET) for _ in range(10))
    return f"{raw[:5]}-{raw[5:]}"


async def _replace_recovery_codes(session: AsyncSession, user: User) -> list[str]:
    """Revoke every unused code and make a new set. Doesn't commit."""
    await session.execute(
        update(RecoveryCode)
        .where(RecoveryCode.user_id == user.id, RecoveryCode.used_at.is_(None), RecoveryCode.revoked_at.is_(None))
        .values(revoked_at=_now())
    )
    codes = [_new_recovery_code() for _ in range(RECOVERY_CODE_COUNT)]
    session.add_all(RecoveryCode(user_id=user.id, code_sha256=_hash(code)) for code in codes)
    return codes


async def new_recovery_codes(session: AsyncSession, user: User) -> list[str]:
    """A fresh set for a signed-in staff member; the old unused ones stop working."""
    codes = await _replace_recovery_codes(session, user)
    record_event(session, actor=user, action="auth.recovery_codes_replaced", entity_type=AUDIT_ENTITY, entity_id=user.id)
    await session.commit()
    return codes


async def recovery_codes_left(session: AsyncSession, user: User) -> int:
    return await session.scalar(
        select(func.count())
        .select_from(RecoveryCode)
        .where(RecoveryCode.user_id == user.id, RecoveryCode.used_at.is_(None), RecoveryCode.revoked_at.is_(None))
    )


async def use_recovery_code(session: AsyncSession, user: User, code: str) -> bool:
    if not await is_enrolled(session, user):
        return False
    used = await session.scalar(
        update(RecoveryCode)
        .where(
            RecoveryCode.user_id == user.id,
            RecoveryCode.code_sha256 == _hash(code),
            RecoveryCode.used_at.is_(None),
            RecoveryCode.revoked_at.is_(None),
        )
        .values(used_at=_now())
        .returning(RecoveryCode.id)
    )
    if used is None:
        return False
    left = await recovery_codes_left(session, user)
    record_event(
        session, actor=user, action="auth.recovery_code_used", entity_type=AUDIT_ENTITY, entity_id=user.id,
        details={"codes_left": left},
    )
    await session.commit()
    return True


async def set_up_with_known_secret(session: AsyncSession, user: User, secret: str) -> None:
    """Development and demo seeds only: an authenticator already set up with a
    published secret, so demo accounts and the walk-throughs can sign in."""
    if await _credential(session, user) is None:
        session.add(TotpCredential(user_id=user.id, secret_encrypted=_encrypt(secret), confirmed_at=_now()))
        await session.commit()
