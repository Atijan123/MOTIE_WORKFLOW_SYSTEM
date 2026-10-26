"""Shapes of request and response bodies. Kept separate from the table classes
so we never accidentally send a column like password_hash to the client."""

from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    email: str
    password: str


class SetPasswordRequest(BaseModel):
    token: str = Field(max_length=200)  # from the link, after "#token="
    password: str = Field(max_length=1000)  # bounded: hashing a huge input wastes CPU


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int  # seconds


class UserOut(BaseModel):
    id: int
    email: str | None  # empty only for a walk-in applicant with no email
    full_name: str
    roles: list[str]
    positions: list[str]  # position codes, e.g. ["director_of_trade"]
    position_titles: list[str]  # the same posts' titles, in the same order, for the screen's header
