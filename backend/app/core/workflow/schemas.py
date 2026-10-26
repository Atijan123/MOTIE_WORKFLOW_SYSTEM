from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, Field


class StartCaseRequest(BaseModel):
    workflow: str  # workflow code, e.g. "etls_application"


class ChangeStatusRequest(BaseModel):
    to_status: str  # status code, e.g. "with_minister"
    # The internal minute: staff only, never shown to the applicant.
    comment: str | None = Field(default=None, max_length=2000)
    # What the applicant is told, on moves that send it (returns, rejections).
    applicant_message: str | None = Field(default=None, max_length=2000)


class StatusOut(BaseModel):
    # Internal step code and staff wording: null for applicants, who never see them.
    code: str | None
    name: str | None
    # What the applicant sees, e.g. "Being verified" and a one-line explanation.
    label: str
    explanation: str | None
    is_final: bool
    editable: bool  # the applicant may still change the form (a draft)


class ActionOut(BaseModel):
    to_status: str
    name: str
    # Set when the user may only make this move for another post, through a
    # delegation or because that post's holders are absent, e.g. "minister".
    # The frontend can label the button "(for the Minister)".
    on_behalf_of: str | None
    # The move needs a written reason in the comment (e.g. cancelling a letter).
    requires_comment: bool
    # The move needs a message to the applicant (a return or a rejection).
    requires_applicant_message: bool = False
    # Why the button is disabled right now, e.g. ["Invoice is missing"]; empty
    # when it can be pressed. Null where it isn't worked out (queues, for speed).
    blocked_by: list[str] | None = None
    # Things to know before pressing it, which don't stop it (e.g. "certificate
    # SN-CO-1 expires on 3rd November, 2026"). Null where not worked out.
    warnings: list[str] | None = None


class CaseOut(BaseModel):
    id: int
    reference: str | None  # e.g. MOTIE/ETLS/FL/2026/0001; null while a draft
    submitted_at: datetime | None
    workflow: str
    status: StatusOut
    created_by: int  # the applicant whose case it is
    entered_by: int | None  # a walk-in: the staff member who typed it in
    created_at: datetime
    updated_at: datetime
    # Why the case was returned or rejected, as the applicant was told: the
    # message of the move that put it in its current status, if it had one.
    applicant_message: str | None
    # What *this* user may do next; the frontend shows one button per action.
    available_actions: list[ActionOut]
    # True while an open blocking flag holds the case. None for applicants:
    # a flag can be a fraud suspicion, which isn't theirs to see.
    on_hold: bool | None
    # Staff only: false when the applicant has no email (a walk-in), so the
    # Ministry's emails can't reach them and Records must tell them instead.
    applicant_emailed: bool | None


class CaseSummaryOut(BaseModel):
    """One row of a list or queue."""

    id: int
    reference: str | None
    workflow: str
    service: str  # e.g. "ETLS facility letter"
    status: StatusOut
    submitted_at: datetime | None
    # When it reached its current step, and the whole days since (queues).
    status_since: datetime
    days_waiting: int
    summary: str | None  # the module's one line, e.g. "Roofing sheets, 1200.5 tonnes"
    applicant_name: str | None  # staff only
    # "My cases": why it was returned or rejected (the notice with "Fix and resubmit").
    applicant_message: str | None
    available_actions: list[ActionOut]  # in a queue: what I can do; empty in "my cases"


class AbsenceSeenOut(BaseModel):
    person: str
    starts_on: date
    ends_on: date


class DelegationSeenOut(BaseModel):
    from_position: str
    to_position: str
    starts_on: date
    ends_on: date


class ActingForOut(BaseModel):
    """Set when the actor made another post's move: whose, and why they could."""

    position: str  # e.g. "permanent_secretary"
    title: str  # e.g. "Permanent Secretary": the screen says "acting for the Permanent Secretary"
    basis: str  # "delegation" or "succession"
    absences: list[AbsenceSeenOut]  # who was away, from when to when (succession)
    delegation: DelegationSeenOut | None


class AuditEventOut(BaseModel):
    occurred_at: datetime
    actor_user_id: int | None
    actor_name: str | None
    actor_title: str | None  # the post they acted from, e.g. "Deputy Permanent Secretary, ..."
    acting_for: ActingForOut | None
    action: str
    details: dict[str, Any]


class TimelineEntryOut(BaseModel):
    """One line of the applicant's timeline: a plain label and when."""

    occurred_at: datetime
    label: str
    message: str | None  # e.g. why it was returned


class ChecklistItemOut(BaseModel):
    code: str
    label: str
    at_current_step: bool  # can be ticked now (else: ticked at an earlier or later step)
    ticked: bool
    ticked_by: int | None
    ticked_at: datetime | None


class TickRequest(BaseModel):
    ticked: bool


class FlagOut(BaseModel):
    id: int
    code: str
    message: str
    details: dict[str, Any]
    for_position: str
    blocking: bool
    raised_at: datetime
    resolved_at: datetime | None
    resolved_by: int | None
    resolution: str | None


class ResolveFlagRequest(BaseModel):
    # A reason is required: "checked with the exporter, same shipment split in two".
    resolution: str = Field(min_length=1, max_length=2000)


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


class AwayPeriodOut(BaseModel):
    person: str
    starts_on: date
    ends_on: date


class ActingNowOut(BaseModel):
    """A post I'm acting for today: "You are acting for the Permanent Secretary (absent ...)"."""

    position: str
    title: str
    basis: str  # "delegation" or "succession"
    workflows: list[str] | None  # null = every workflow
    absences: list[AwayPeriodOut]  # succession: whose absence, from when to when
    delegation_starts_on: date | None  # delegation: its dates
    delegation_ends_on: date | None


class StandInOut(BaseModel):
    position: str
    title: str
    holders: list[str]


class SuccessionLineOut(BaseModel):
    workflow: str
    line: list[StandInOut]  # first in line first


class MyDelegationOut(BaseModel):
    id: int  # for POST /delegations/{id}/revoke
    to_position: str
    to_title: str
    workflow: str | None
    starts_on: date
    ends_on: date


class CoverForPostOut(BaseModel):
    """Who acts for one of my posts when I'm away: a delegation first, otherwise the succession line."""

    position: str
    title: str
    delegations: list[MyDelegationOut]
    succession: list[SuccessionLineOut]


class AbsenceViewOut(BaseModel):
    """An absence as all staff see it (S11). `reason` only for the person and for recorders."""

    id: int
    person: str
    posts: list[str]
    starts_on: date
    ends_on: date
    reason: str | None
    may_cancel: bool  # your own absence, or you're a recorder: the cancel button shows


class HolderOut(BaseModel):
    user_id: int
    name: str


class PostChoiceOut(BaseModel):
    code: str
    title: str
    holders: list[HolderOut]


class WorkflowChoiceOut(BaseModel):
    code: str
    name: str


class ChoicesOut(BaseModel):
    """What S11's forms pick from: posts (with holders) and workflows."""

    posts: list[PostChoiceOut]
    workflows: list[WorkflowChoiceOut]
