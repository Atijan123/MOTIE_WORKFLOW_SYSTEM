"""Shapes of request and response bodies. Kept separate from the table classes
so we never accidentally send a column like password_hash to the client."""

from pydantic import BaseModel


class LoginRequest(BaseModel):
    email: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int  # seconds


class UserOut(BaseModel):
    id: int
    email: str
    full_name: str
    roles: list[str]
