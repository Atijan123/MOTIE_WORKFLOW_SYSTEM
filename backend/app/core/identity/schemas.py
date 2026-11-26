"""Shapes of request and response bodies. Kept separate from the table classes
so we never accidentally send a column like password_hash to the client."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    email: str = Field(max_length=320)
    password: str = Field(max_length=1000)  # bounded: hashing a huge input wastes CPU


class SetPasswordRequest(BaseModel):
    token: str = Field(max_length=200)  # from the link, after "#token="
    password: str = Field(max_length=1000)  # bounded: hashing a huge input wastes CPU


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int  # seconds


class LoginResponse(BaseModel):
    """What /auth/login answers (step 12e). Applicants: `next="done"` and a
    token. Staff: no token yet, but a `challenge` for the second step:
    `next="code"` (give the authenticator code) or `next="set_up"` (first
    time: set up an authenticator)."""

    next: Literal["done", "code", "set_up"]
    access_token: str | None = None
    token_type: str = "bearer"
    expires_in: int | None = None  # seconds
    challenge: str | None = None


class ChallengeRequest(BaseModel):
    challenge: str = Field(max_length=2000)


class ChallengeCodeRequest(ChallengeRequest):
    code: str = Field(max_length=40)


class SetUpStart(BaseModel):
    secret: str  # to type in by hand, if the QR code can't be scanned
    otpauth_uri: str
    qr_svg: str


class SetUpDone(LoginResponse):
    recovery_codes: list[str]  # shown once, never again


class CodeRequest(BaseModel):
    code: str = Field(max_length=40)


class RecoveryCodesOut(BaseModel):
    recovery_codes: list[str]


class TwoStepStatus(BaseModel):
    set_up: bool
    recovery_codes_left: int


class UserOut(BaseModel):
    id: int
    email: str | None  # empty only for a walk-in applicant with no email
    full_name: str
    roles: list[str]
    positions: list[str]  # position codes, e.g. ["director_of_trade"]
    position_titles: list[str]  # the same posts' titles, in the same order, for the screen's header


class PasswordRequest(BaseModel):
    password: str = Field(max_length=1000)


class SessionOut(BaseModel):
    ends_at: datetime  # signed out then, whatever (staff: 8 hours after signing in)
    idle_minutes: int | None  # signed out after this long without a request (staff only)
    password_fresh_until: datetime  # signing or approving asks for the password again after this
