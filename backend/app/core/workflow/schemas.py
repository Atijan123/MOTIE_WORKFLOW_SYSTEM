from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class StartCaseRequest(BaseModel):
    workflow: str  # workflow code, e.g. "etls_application"


class ChangeStatusRequest(BaseModel):
    to_status: str  # status code, e.g. "with_minister"
    comment: str | None = Field(default=None, max_length=2000)


class StatusOut(BaseModel):
    code: str
    name: str
    is_final: bool


class ActionOut(BaseModel):
    to_status: str
    name: str


class CaseOut(BaseModel):
    id: int
    workflow: str
    status: StatusOut
    created_by: int
    created_at: datetime
    updated_at: datetime
    # What *this* user may do next; the frontend shows one button per action.
    available_actions: list[ActionOut]


class AuditEventOut(BaseModel):
    occurred_at: datetime
    actor_user_id: int | None
    action: str
    details: dict[str, Any]
