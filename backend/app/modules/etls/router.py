from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.identity.deps import get_current_user
from app.core.identity.models import User
from app.core.workflow import router as workflow_router
from app.core.workflow import service as workflow
from app.core.workflow.schemas import CaseOut
from app.db.session import get_session
from app.modules.etls import letter as facility_letter
from app.modules.etls import service
from app.modules.etls.models import FacilityLetter
from app.core.documents.models import IssuedDocument
from app.modules.etls.schemas import (
    CertificateOut,
    ChecksSummaryOut,
    DispatchRequest,
    DuplicateNumberOut,
    OtherCaseOut,
    FacilityLetterForm,
    FacilityLetterOut,
    HsCodeConfirmation,
    IssuedLetterOut,
)

# Engine errors (WorkflowError) are turned into HTTP statuses by the handler in main.py.
router = APIRouter(prefix="/etls", tags=["etls"])


async def _out(session: AsyncSession, letter: FacilityLetter, user: User) -> FacilityLetterOut:
    case = await workflow.get_case(session, letter.case_id, user)
    return FacilityLetterOut(
        case_id=letter.case_id,
        reference=case.reference,
        # Applicants get the plain label only (core service.status_view()).
        status=case.current_status.code if workflow.is_staff(user) else None,
        status_label=case.current_status.applicant_label,
        importer_name=letter.importer_name,
        importer_address=letter.importer_address,
        product=letter.product,
        hs_code=letter.hs_code,
        hs_code_confirmed=letter.hs_code_confirmed,
        quantity=letter.quantity,
        unit=letter.unit,
        exporter_name=letter.exporter_name,
        exporter_country=letter.exporter_country,
        exporter_etls_approval_number=letter.exporter_etls_approval_number,
        product_approval_numbers=[a.number for a in letter.product_approvals],
        certificates_of_origin=[
            CertificateOut(number=c.number, issued_on=c.issued_on, expires_on=service.certificate_expiry(c))
            for c in letter.certificates
        ],
    )


@router.post("/facility-letters", response_model=FacilityLetterOut, status_code=status.HTTP_201_CREATED)
async def create_facility_letter(
    body: FacilityLetterForm,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """Start an application as a draft. Upload its documents, then submit it
    with `POST /cases/{id}/status` and `{"to_status": "submitted"}`."""
    letter = await service.create_draft(session, actor=user, form=body)
    return await _out(session, letter, user)


@router.put("/facility-letters/{case_id}", response_model=FacilityLetterOut)
async def update_facility_letter(
    case_id: int,
    body: FacilityLetterForm,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """Replace the whole form, while the application is still a draft."""
    letter = await service.update_form(session, case_id=case_id, actor=user, form=body)
    return await _out(session, letter, user)


@router.get("/facility-letters/{case_id}", response_model=FacilityLetterOut)
async def get_facility_letter(
    case_id: int,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    return await _out(session, await service.get_facility_letter(session, case_id, user), user)


@router.get("/facility-letters/{case_id}/checks", response_model=ChecksSummaryOut)
async def checks_summary(
    case_id: int,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """Everything checked so far, for the PS before signing (staff only)."""
    return await service.checks_summary(session, case_id, user)


@router.get(
    "/facility-letters/{case_id}/letter-preview.pdf",
    response_class=Response,
    responses={200: {"content": {"application/pdf": {}}}},
)
async def preview_facility_letter(
    case_id: int,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """The letter as it would read if signed today, marked as a draft at the
    top. Never stored; only signing issues the letter (staff only)."""
    content = await facility_letter.preview(session, case_id, user)
    return Response(
        content=content,
        media_type="application/pdf",
        headers={
            # Shown in the browser, not saved by default; never cached.
            "Content-Disposition": 'inline; filename="facility-letter-preview.pdf"',
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
            "X-Letter-Status": "preview",
        },
    )


@router.get("/facility-letters/{case_id}/duplicates", response_model=list[DuplicateNumberOut])
async def duplicate_certificates(
    case_id: int,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """Certificate numbers on this case that other submitted cases also used,
    with each earlier case's reference, current status and date (staff only)."""
    found = await service.other_uses(session, case_id, user)
    return [
        DuplicateNumberOut(
            number=number,
            other_cases=[
                OtherCaseOut(
                    case_id=case.id,
                    reference=case.reference,
                    status=status.name,
                    status_code=status.code,
                    submitted_at=case.submitted_at,
                    importer_name=importer,
                )
                for case, status, importer in cases
            ],
        )
        for number, cases in found.items()
    ]


@router.post("/facility-letters/{case_id}/hs-code", response_model=FacilityLetterOut)
async def confirm_hs_code(
    case_id: int,
    body: HsCodeConfirmation,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """The verifying officer confirms (or corrects) the HS code. Dots and spaces are ignored."""
    letter = await service.confirm_hs_code(session, case_id, user, body.hs_code)
    return await _out(session, letter, user)


@router.get(
    "/facility-letters/{case_id}/letter.pdf",
    response_class=Response,
    responses={200: {"content": {"application/pdf": {}}}},
)
async def download_facility_letter(
    case_id: int,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """The letter in force: the file stored when it was signed, never re-made.

    If a letter was cancelled and corrected, this is the corrected one; the
    earlier ones are listed at /letters. The X-Checksum-SHA256 header matches
    the checksum in the audit log, so anyone holding a copy can check it's
    the one issued."""
    document, content = await facility_letter.current_letter(session, case_id, user)
    return _pdf(document, content)


@router.get("/facility-letters/{case_id}/letters", response_model=list[IssuedLetterOut])
async def list_letters(
    case_id: int,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """Every letter issued on this case, oldest first, with cancelled ones marked."""
    letters = await facility_letter.letters(session, case_id, user)
    sent = await facility_letter.dispatches(session, case_id)
    return [_letter_out(case_id, d, sent.get(d.id)) for d in letters]


@router.post("/facility-letters/{case_id}/sent-to-gra", response_model=CaseOut)
async def mark_sent_to_gra(
    case_id: int,
    body: DispatchRequest,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """Records' "Mark sent to GRA": records the dispatch date against the
    current letter and moves the case to "Sent to GRA"."""
    case = await facility_letter.mark_sent_to_gra(
        session, case_id=case_id, actor=user, dispatched_on=body.dispatched_on
    )
    return await workflow_router.case_out(session, case, user)


@router.get(
    "/facility-letters/{case_id}/letters/{letter_id}/file",
    response_class=Response,
    responses={200: {"content": {"application/pdf": {}}}},
)
async def download_one_letter(
    case_id: int,
    letter_id: int,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """One letter, current or cancelled. X-Letter-Status says which."""
    document, content = await facility_letter.letter_by_id(session, case_id, letter_id, user)
    return _pdf(document, content)


def _pdf(document: IssuedDocument, content: bytes) -> Response:
    return Response(
        content=content,
        media_type=document.content_type,
        headers={
            "Content-Disposition": f'attachment; filename="{document.filename}"',
            "X-Content-Type-Options": "nosniff",
            "X-Checksum-SHA256": document.sha256,
            # The bytes of a cancelled letter can't be marked (that would break
            # its checksum), so the response says it instead.
            "X-Letter-Status": "cancelled" if document.cancelled_at else "current",
        },
    )


def _letter_out(case_id: int, d: IssuedDocument, dispatch=None) -> IssuedLetterOut:
    return IssuedLetterOut(
        id=d.id,
        filename=d.filename,
        status="cancelled" if d.cancelled_at else "current",
        issued_at=d.issued_at,
        issued_by=d.issued_by,
        sha256=d.sha256,
        template_version=d.template_version,
        replaces_id=d.replaces_id,
        cancelled_at=d.cancelled_at,
        cancelled_by=d.cancelled_by,
        cancellation_reason=d.cancellation_reason,
        sent_to_gra_on=dispatch.dispatched_on if dispatch else None,
        download_url=f"/etls/facility-letters/{case_id}/letters/{d.id}/file",
    )
