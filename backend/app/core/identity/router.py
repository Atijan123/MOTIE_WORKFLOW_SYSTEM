"""Signing in and out.

Applicants: POST /auth/login with email and password -> a token.
Staff (step 12e): POST /auth/login -> a challenge, then one of
    POST /auth/login/code            the code from their authenticator app
    POST /auth/login/recovery-code   a one-time recovery code
    POST /auth/two-step/set-up, then /auth/two-step/confirm   (the first time)
-> a token. Every step checks the network (12c) and the lockout (12d) again,
and every try is recorded.
"""

import jwt
from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.identity import login_guard, password_links, sessions, two_step
from app.core.identity.channel import OUTSIDE_NETWORK_MESSAGE, Channel, came_through, staff_ip_allowed
from app.core.identity.deps import get_channel, get_current_session, get_current_user
from app.core.identity.models import LoginSession, User
from app.core.identity.schemas import (
    ChallengeCodeRequest,
    ChallengeRequest,
    CodeRequest,
    LoginRequest,
    LoginResponse,
    PasswordRequest,
    RecoveryCodesOut,
    SetPasswordRequest,
    SetUpDone,
    SessionOut,
    SetUpStart,
    TwoStepStatus,
    UserOut,
)
from app.core.identity.security import create_challenge_token, decode_challenge_token
from app.core.identity.service import WeakPassword, authenticate
from app.db.session import get_session

router = APIRouter(prefix="/auth", tags=["auth"])

BAD_CODE = "That code didn't work. Check that your phone's clock is right, and use the newest code."
CHALLENGE_ENDED = "Your sign-in took too long or has ended. Please start again."


def _refuse_outside(channel: Channel) -> None:
    if channel.portal == "staff" and not staff_ip_allowed(channel):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=OUTSIDE_NETWORK_MESSAGE)


async def _refuse_if_locked(session: AsyncSession, email: str, channel: Channel) -> None:
    try:
        await login_guard.check(session, email, channel)
    except login_guard.LoginRefused as refused:
        await login_guard.record(session, email=email, channel=channel, outcome="refused")
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=refused.message,
            headers={"Retry-After": str(refused.minutes * 60)},
        )


async def _signed_in(session: AsyncSession, user: User, channel: Channel) -> dict:
    token, seconds = await sessions.start(session, user, channel.portal)
    return {"next": "done", "access_token": token, "expires_in": seconds}


@router.post("/login", response_model=LoginResponse)
async def login(
    body: LoginRequest,
    channel: Channel = Depends(get_channel),
    session: AsyncSession = Depends(get_session),
):
    # The staff app from outside the Ministry network: refuse before looking
    # at the password at all, so it can't be used to guess passwords (step 12c).
    if channel.portal == "staff" and not staff_ip_allowed(channel):
        await login_guard.record(session, email=body.email, channel=channel, outcome="outside_network")
        _refuse_outside(channel)
    # Locked account or too many tries from this IP: refuse before the
    # password is checked, so a locked account can't be guessed at (step 12d).
    await _refuse_if_locked(session, body.email, channel)
    user = await authenticate(session, body.email, body.password)
    # A staff account through the applicant portal (or the reverse) gets the
    # same answer as a wrong password: a phished or guessed staff password is
    # no use from the public site. The login pages say which app is whose.
    if user is not None and not came_through(channel, user.portal):
        # Recorded against the account: a right staff password on the public
        # site is a sign it has leaked. (Counted as a failure all the same.)
        await login_guard.record(session, email=body.email, channel=channel, outcome="wrong_portal", user=user)
        user = None
    elif user is None:
        await login_guard.record(session, email=body.email, channel=channel, outcome="bad_password")
    if user is None:
        # One message for every failure (unknown email, wrong password,
        # deactivated account), so it reveals nothing.
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Incorrect email or password")

    if not user.is_staff:
        await login_guard.record(session, email=body.email, channel=channel, outcome="success", user=user)
        return await _signed_in(session, user, channel)

    # Staff: the password alone is not enough (step 12e).
    try:
        enrolled = await two_step.is_enrolled(session, user)
        two_step.ensure_available()
    except two_step.TwoStepUnavailable as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc))
    await login_guard.record(session, email=body.email, channel=channel, outcome=login_guard.PASSWORD_OK, user=user)
    return {"next": "code" if enrolled else "set_up", "challenge": create_challenge_token(user.id, channel.portal)}


async def _challenged_user(session: AsyncSession, challenge: str, channel: Channel) -> User:
    """The staff member a challenge token is for, if it's still good, through
    the same app, from the right network, and their account isn't locked."""
    _refuse_outside(channel)
    try:
        user_id = decode_challenge_token(challenge, channel.portal)
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=CHALLENGE_ENDED)
    user = await session.get(User, user_id)
    if user is None or not user.is_active or not came_through(channel, user.portal):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=CHALLENGE_ENDED)
    # Wrong codes count towards the same lock as wrong passwords.
    await _refuse_if_locked(session, user.email, channel)
    return user


async def _code_failed(session: AsyncSession, user: User, channel: Channel) -> HTTPException:
    await login_guard.record(session, email=user.email, channel=channel, outcome="bad_code", user=user)
    return HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=BAD_CODE)


@router.post("/login/code", response_model=LoginResponse)
async def login_with_code(
    body: ChallengeCodeRequest, channel: Channel = Depends(get_channel), session: AsyncSession = Depends(get_session)
):
    user = await _challenged_user(session, body.challenge, channel)
    if not await two_step.verify_code(session, user, body.code):
        raise await _code_failed(session, user, channel)
    await login_guard.record(session, email=user.email, channel=channel, outcome="success", user=user)
    return await _signed_in(session, user, channel)


@router.post("/login/recovery-code", response_model=LoginResponse)
async def login_with_recovery_code(
    body: ChallengeCodeRequest, channel: Channel = Depends(get_channel), session: AsyncSession = Depends(get_session)
):
    user = await _challenged_user(session, body.challenge, channel)
    if not await two_step.use_recovery_code(session, user, body.code):
        raise await _code_failed(session, user, channel)
    await login_guard.record(session, email=user.email, channel=channel, outcome="success", user=user)
    return await _signed_in(session, user, channel)


@router.post("/two-step/set-up", response_model=SetUpStart)
async def start_set_up(
    body: ChallengeRequest, channel: Channel = Depends(get_channel), session: AsyncSession = Depends(get_session)
):
    """The first sign-in: a new authenticator secret, as a QR code and as text."""
    user = await _challenged_user(session, body.challenge, channel)
    try:
        secret, uri = await two_step.start_enrolment(session, user)
    except two_step.AlreadyEnrolled as exc:
        # Someone with the password must not be able to replace the authenticator.
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    return SetUpStart(secret=secret, otpauth_uri=uri, qr_svg=two_step.qr_svg(uri))


@router.post("/two-step/confirm", response_model=SetUpDone)
async def confirm_set_up(
    body: ChallengeCodeRequest, channel: Channel = Depends(get_channel), session: AsyncSession = Depends(get_session)
):
    """The first code from the new authenticator: proves it was set up right.
    Signs in, and returns the recovery codes, which are shown this once."""
    user = await _challenged_user(session, body.challenge, channel)
    codes = await two_step.confirm_enrolment(session, user, body.code)
    if codes is None:
        raise await _code_failed(session, user, channel)
    await login_guard.record(session, email=user.email, channel=channel, outcome="success", user=user)
    return {**(await _signed_in(session, user, channel)), "recovery_codes": codes}


@router.get("/two-step", response_model=TwoStepStatus)
async def two_step_status(user: User = Depends(get_current_user), session: AsyncSession = Depends(get_session)):
    return TwoStepStatus(
        set_up=await two_step.is_enrolled(session, user),
        recovery_codes_left=await two_step.recovery_codes_left(session, user),
    )


@router.post("/two-step/recovery-codes", response_model=RecoveryCodesOut)
async def replace_recovery_codes(
    body: CodeRequest,
    channel: Channel = Depends(get_channel),
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """A new set of recovery codes; the old unused ones stop working. Needs a
    current authenticator code, so a stolen session alone can't make codes."""
    if not user.is_staff:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not allowed")
    await _refuse_if_locked(session, user.email, channel)
    if not await two_step.verify_code(session, user, body.code):
        raise await _code_failed(session, user, channel)
    return RecoveryCodesOut(recovery_codes=await two_step.new_recovery_codes(session, user))


def _session_out(login: LoginSession, user: User) -> SessionOut:
    idle = sessions.idle_limit(user)
    return SessionOut(
        ends_at=login.expires_at,
        idle_minutes=int(idle.total_seconds() // 60) if idle else None,
        password_fresh_until=sessions.password_fresh_until(login),
    )


@router.get("/session", response_model=SessionOut)
async def current_session(
    login: LoginSession = Depends(get_current_session), user: User = Depends(get_current_user)
):
    """When this session ends, and until when the password counts as recent (step 12f)."""
    return _session_out(login, user)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    login: LoginSession = Depends(get_current_session),
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """Ends the session on the server: the token stops working at once, even
    if someone copied it."""
    await sessions.end(session, login, user)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/reauth", response_model=SessionOut)
async def recheck_password(
    body: PasswordRequest,
    channel: Channel = Depends(get_channel),
    login: LoginSession = Depends(get_current_session),
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """Type the password again before signing or approving (step 12f). Wrong
    passwords count towards the lockout, as at sign-in."""
    await _refuse_if_locked(session, user.email, channel)
    if await authenticate(session, user.email, body.password) is None:
        await login_guard.record(session, email=user.email, channel=channel, outcome="bad_password", user=user)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="That password isn't right.")
    await sessions.password_checked(session, login, user)
    return _session_out(login, user)


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
    if not settings.applicant_portal_on():
        # Office mode: applicants don't sign in, so no link may set a password.
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not available on this server.")
    try:
        await password_links.set_password(session, token=body.token, password=body.password)
    except WeakPassword as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))
    except password_links.InvalidLink as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    return Response(status_code=status.HTTP_204_NO_CONTENT)
