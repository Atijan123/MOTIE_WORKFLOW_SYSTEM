from datetime import date, datetime
from decimal import Decimal
from typing import Literal
from typing import Annotated, Any

from pydantic import AfterValidator, BaseModel, BeforeValidator, Field, StringConstraints, field_validator

from app.core.workflow.delegation import today

# Stripped of surrounding spaces, never empty, and bounded so nobody can store a
# novel in a form field.
ShortText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
LongText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1000)]
Number = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=60)]


def _blank_is_empty(value: Any) -> Any:
    """A draft's empty box arrives as "" or "  ": store it as not filled in."""
    return None if isinstance(value, str) and not value.strip() else value


# A form field a draft may leave empty. Submit checks it's filled in
# (etls_form_complete in service.py); its shape is checked whenever it's given.
Blank = BeforeValidator(_blank_is_empty)


def normalize_hs_code(code: str) -> str:
    """"2523.29", "2523 29" and "252329" are the same HS code: keep the digits.

    6 digits is the international HS code; 8 or 10 are national/ECOWAS tariff lines.
    """
    digits = "".join(code.replace(".", "").split())
    if not digits.isascii() or not digits.isdigit() or len(digits) not in (6, 8, 10):
        raise ValueError("an HS code is 6, 8 or 10 digits, e.g. 2523.29")
    return digits


HsCode = Annotated[str, StringConstraints(max_length=20), AfterValidator(normalize_hs_code)]


def normalize_certificate_number(number: str) -> str:
    """"cg 2026/0042 " and "CG2026/0042" are the same certificate."""
    return "".join(number.split()).upper()


class CertificateOfOrigin(BaseModel):
    number: Number
    # Valid for six months from this date. A draft may leave it empty for now.
    issued_on: Annotated[date | None, Blank] = None

    @field_validator("issued_on")
    @classmethod
    def _not_in_the_future(cls, issued_on: date | None) -> date | None:
        if issued_on is not None and issued_on > today():
            raise ValueError("a certificate can't be issued in the future")
        return issued_on


class FacilityLetterForm(BaseModel):
    """The application form, as the applicant saves it.

    Any field may be empty while it's a draft, so the applicant can save and
    come back. What's given must still have the right shape (a positive
    quantity, a real HS code). Submit is blocked until the form is complete
    (etls_form_complete), and its blocked_by lists what's still empty.
    """

    importer_name: Annotated[ShortText | None, Blank] = None
    importer_address: Annotated[LongText | None, Blank] = None
    product: Annotated[ShortText | None, Blank] = None
    # Optional even at Submit: the applicant may not know it. The ETLS desk
    # enters or confirms it before verifying the file.
    hs_code: Annotated[HsCode | None, Blank] = None
    quantity: Annotated[Annotated[Decimal, Field(gt=0, max_digits=14, decimal_places=3)] | None, Blank] = None
    unit: Annotated[
        Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=30)] | None, Blank
    ] = None
    exporter_name: Annotated[ShortText | None, Blank] = None
    exporter_country: Annotated[ShortText | None, Blank] = None
    exporter_etls_approval_number: Annotated[Number | None, Blank] = None
    product_approval_numbers: list[Number] = Field(default_factory=list, max_length=50)
    certificates_of_origin: list[CertificateOfOrigin] = Field(default_factory=list, max_length=50)

    @field_validator("product_approval_numbers")
    @classmethod
    def _no_repeated_approvals(cls, numbers: list[str]) -> list[str]:
        if len(set(numbers)) != len(numbers):
            raise ValueError("a product approval number is listed twice")
        return numbers

    @field_validator("certificates_of_origin")
    @classmethod
    def _no_repeated_certificates(cls, certificates: list) -> list:
        normalized = [normalize_certificate_number(c.number) for c in certificates]
        if len(set(normalized)) != len(normalized):
            raise ValueError("a certificate of origin number is listed twice")
        return certificates


class CertificateOut(BaseModel):
    number: str
    issued_on: date | None  # empty only on applications from before issue dates were asked
    expires_on: date | None  # six months after issue


class WalkInApplication(BaseModel):
    """Records opens an application for an applicant who came in person."""

    # A loose shape check: the address is for notifications, and a typo shows
    # up as an email that never arrives, which Records can correct. Empty if
    # the applicant has none: their account then can't log in or be emailed,
    # and Records tells them of each step.
    applicant_email: Annotated[
        Annotated[
            str,
            StringConstraints(strip_whitespace=True, to_lower=True, max_length=254, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$"),
        ]
        | None,
        Blank,
    ] = None
    applicant_name: ShortText
    form: FacilityLetterForm


class FacilityLetterOut(FacilityLetterForm):
    """The form as stored. On a draft, any field may still be empty."""

    case_id: int
    reference: str | None  # the case's tracking number, e.g. MOTIE/ETLS/FL/2026/0001
    status: str | None  # internal status code, for staff only; GET /cases/{id} has the full case
    status_label: str  # what the applicant sees, e.g. "Being verified"
    # Cases from before step 6g have no declared code.
    hs_code: str | None
    hs_code_confirmed: str | None
    certificates_of_origin: list[CertificateOut]


class OtherCaseOut(BaseModel):
    case_id: int
    reference: str
    status: str  # staff wording, e.g. "Rejected"
    status_code: str
    submitted_at: datetime
    importer_name: str


class DuplicateNumberOut(BaseModel):
    number: str  # as typed on this case
    other_cases: list[OtherCaseOut]  # oldest first


class OriginalSeenOut(BaseModel):
    document: str
    seen: bool  # the newest upload's paper original has been seen
    seen_at: datetime | None
    seen_by: str | None  # name


class TickSummaryOut(BaseModel):
    label: str
    ticked: bool
    ticked_at: datetime | None
    ticked_by: str | None  # name


class FlagSummaryOut(BaseModel):
    message: str
    resolved: bool
    resolution: str | None  # the finding, e.g. "Same shipment, split in two"


class CertificateCheckOut(BaseModel):
    number: str
    issued_on: date | None
    expires_on: date | None
    valid_today: bool


class ChecksSummaryOut(BaseModel):
    """What has been checked on the application (SCREENS.md S3)."""

    originals: list[OriginalSeenOut]
    checklist: list[TickSummaryOut]  # the ECOWAS ETLS list ticks
    duplicate_flags: list[FlagSummaryOut]  # empty: no certificate number was used before
    hs_code_confirmed: str | None
    hs_code_confirmed_by: str | None
    certificates: list[CertificateCheckOut]
    documents_missing: list[str]


class DispatchRequest(BaseModel):
    dispatched_on: date  # the day the letter went to GRA


class HsCodeConfirmation(BaseModel):
    hs_code: HsCode


class IssuedLetterOut(BaseModel):
    id: int
    filename: str
    status: Literal["current", "cancelled"]
    issued_at: datetime
    issued_by: int
    sha256: str
    template_version: str
    replaces_id: int | None  # the cancelled letter this one corrects
    cancelled_at: datetime | None
    cancelled_by: int | None
    cancellation_reason: str | None
    sent_to_gra_on: date | None  # the dispatch date, once Records has sent it
    download_url: str


class FormOptionsOut(BaseModel):
    """What the form's Country and Unit boxes offer: the active entries, in order."""

    countries: list[str]
    units: list[str]


class ListItemOut(BaseModel):
    id: int
    name: str
    active: bool  # switched off: no longer offered, and refused on new saves
    sort_order: int


class ListsOut(BaseModel):
    countries: list[ListItemOut]
    units: list[ListItemOut]


class NewListItem(BaseModel):
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]


class ListItemChange(BaseModel):
    """Leave out what doesn't change."""

    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)] | None = None
    active: bool | None = None
