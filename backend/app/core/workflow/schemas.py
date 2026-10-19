from datetime import date, datetime
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
    # Set when the user may only make this move for another post, through a
    # delegation or because that post's holders are absent, e.g. "minister".
    # The frontend can label the button "(for the Minister)".
    on_behalf_of: str | None


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


class CreateDelegationRequest(BaseModel):
    from_position: str  # position code; you must hold it
    to_position: str
    starts_on: date  # both days included
    ends_on: date
    workflow: str | None = None  # workflow code; empty = all workflows
    reason: str | None = Field(default=None, max_length=500)


class DelegationOut(BaseModel):
    id: int
    from_position: str
    to_position: str
    workflow: str | None
    starts_on: date
    ends_on: date
    reason: str | None
    created_by: int
    created_at: datetime
    revoked_at: datetime | None


class RecordAbsenceRequest(BaseModel):
    # Who is away; leave empty for yourself. Someone else needs the absence_recorder role.
    user_id: int | None = None
    starts_on: date  # both days included
    ends_on: date
    reason: str | None = Field(default=None, max_length=500)


class AbsenceOut(BaseModel):
    id: int
    user_id: int
    starts_on: date
    ends_on: date
    reason: str | None
    recorded_by: int
    created_at: datetime
    cancelled_at: datetime | None
