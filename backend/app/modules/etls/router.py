from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.identity.deps import get_current_user
from app.core.identity.models import User
from app.core.workflow import service as workflow
from app.db.session import get_session
from app.modules.etls import letter as facility_letter
from app.modules.etls import service
from app.modules.etls.models import FacilityLetter
from app.core.documents.models import IssuedDocument
from app.modules.etls.schemas import FacilityLetterForm, FacilityLetterOut, HsCodeConfirmation, IssuedLetterOut

# Engine errors (WorkflowError) are turned into HTTP statuses by the handler in main.py.
router = APIRouter(prefix="/etls", tags=["etls"])


async def _out(session: AsyncSession, letter: FacilityLetter, user: User) -> FacilityLetterOut:
    case = await workflow.get_case(session, letter.case_id, user)
    return FacilityLetterOut(
        case_id=letter.case_id,
        status=case.current_status.code,
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
        certificate_of_origin_numbers=[c.number for c in letter.certificates],
    )


@router.post("/facility-letters", response_model=FacilityLetterOut, status_code=status.HTTP_201_CREATED)
async def submit_facility_letter(
    body: FacilityLetterForm,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    letter = await service.submit_facility_letter(session, actor=user, form=body)
    return await _out(session, letter, user)


@router.get("/facility-letters/{case_id}", response_model=FacilityLetterOut)
async def get_facility_letter(
    case_id: int,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    return await _out(session, await service.get_facility_letter(session, case_id, user), user)


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
    return [_letter_out(case_id, d) for d in await facility_letter.letters(session, case_id, user)]


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


def _letter_out(case_id: int, d: IssuedDocument) -> IssuedLetterOut:
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
        download_url=f"/etls/facility-letters/{case_id}/letters/{d.id}/file",
    )
