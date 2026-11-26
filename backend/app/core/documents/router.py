from datetime import datetime

from fastapi import APIRouter, Depends, Request, Response, status
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.documents import scanning, service, storage
from app.core.documents.models import CaseDocument
from app.core.identity.deps import get_current_user
from app.core.identity.models import User
from app.core.workflow import service as workflow
from app.core.workflow.errors import UploadTooLarge
from app.db.session import get_session

# Errors are WorkflowError subclasses, turned into HTTP statuses by the handler in main.py.
router = APIRouter(prefix="/cases", tags=["documents"])


class DocumentOut(BaseModel):
    id: int
    type: str
    filename: str
    content_type: str
    size_bytes: int
    sha256: str
    uploaded_by: int
    uploaded_at: datetime
    original_seen_at: datetime | None
    original_seen_by: int | None


class RequirementOut(BaseModel):
    type: str
    name: str
    # False when a condition (e.g. "HS heading is 2523") doesn't hold; null when
    # it can't be told yet (e.g. no HS code entered yet).
    applies: bool | None
    missing: bool
    original_required: bool  # the paper original must be seen in person
    original_pending: bool  # ...and the newest upload's original hasn't been seen yet
    documents: list[DocumentOut]  # newest first


def _document_out(d: CaseDocument) -> DocumentOut:
    return DocumentOut(
        id=d.id,
        type=d.document_type.code,
        filename=d.filename,
        content_type=d.content_type,
        size_bytes=d.size_bytes,
        sha256=d.sha256,
        uploaded_by=d.uploaded_by,
        uploaded_at=d.uploaded_at,
        original_seen_at=d.original_seen_at,
        original_seen_by=d.original_seen_by,
    )


@router.get("/{case_id}/documents", response_model=list[RequirementOut])
async def document_checklist(
    case_id: int,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """What this case needs, and what has been uploaded."""
    case = await workflow.get_case(session, case_id, user)
    return [
        RequirementOut(
            type=s.requirement.document_type.code,
            name=s.requirement.document_type.name,
            applies=s.applies,
            missing=s.missing,
            original_required=s.requirement.original_required,
            original_pending=s.original_pending,
            documents=[_document_out(d) for d in s.documents],
        )
        for s in await service.checklist(session, case)
    ]


@router.post(
    "/{case_id}/documents/{type_code}",
    response_model=DocumentOut,
    status_code=status.HTTP_201_CREATED,
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {t: {"schema": {"type": "string", "format": "binary"}} for t in
                        ("application/pdf", "image/png", "image/jpeg")},
        }
    },
)
async def upload_document(
    case_id: int,
    type_code: str,
    request: Request,
    filename: str | None = None,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """Upload one file as the raw request body (not a form): PDF, PNG or JPEG.

    `?filename=invoice.pdf` is only for display. Uploading again adds a newer
    version; earlier ones are kept.
    """
    # Refuse an honest-but-too-big upload before reading it. A client can lie
    # about Content-Length, so storage.save() counts the real bytes too.
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > settings.max_upload_bytes:
        raise UploadTooLarge(f"Files can be at most {settings.max_upload_bytes // (1024 * 1024)} MB.")
    document = await service.upload(
        session,
        case_id=case_id,
        type_code=type_code,
        filename=filename,
        chunks=request.stream(),
        actor=user,
    )
    return _document_out(document)


@router.get("/{case_id}/documents/{document_id}/file")
async def download_document(
    case_id: int,
    document_id: int,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    document = await service.get_document(session, case_id=case_id, document_id=document_id, user=user)
    return FileResponse(
        storage.path_for(document.storage_key),
        media_type=document.content_type,
        # "attachment": the browser saves it instead of opening it in our site,
        # and nosniff stops it second-guessing the type we detected.
        filename=document.filename,
        content_disposition_type="attachment",
        headers={"X-Content-Type-Options": "nosniff"},
    )


# --- Scanning with a phone's camera (step 13g, documents/scanning.py) -----------------


class ScanPageOut(BaseModel):
    page_no: int
    size_bytes: int


def _pages_out(pages) -> list[ScanPageOut]:
    return [ScanPageOut(page_no=p.page_no, size_bytes=p.size_bytes) for p in pages]


def _photo_not_too_big(request: Request) -> None:
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > settings.scan_max_photo_bytes:
        raise UploadTooLarge(f"A photo can be at most {settings.scan_max_photo_bytes // (1024 * 1024)} MB.")


@router.get("/{case_id}/documents/{type_code}/scan", response_model=list[ScanPageOut])
async def scan_pages(
    case_id: int, type_code: str, user: User = Depends(get_current_user), session: AsyncSession = Depends(get_session)
):
    """The pages photographed so far for this document (yours only)."""
    return _pages_out(await scanning.pages(session, case_id, type_code, user))


@router.post("/{case_id}/documents/{type_code}/scan/pages", response_model=list[ScanPageOut], status_code=status.HTTP_201_CREATED)
async def add_scan_page(
    case_id: int, type_code: str, request: Request,
    user: User = Depends(get_current_user), session: AsyncSession = Depends(get_session),
):
    """One photo (the raw body: JPEG, PNG or HEIC) as the next page."""
    _photo_not_too_big(request)
    return _pages_out(await scanning.add_page(session, case_id=case_id, type_code=type_code, chunks=request.stream(), actor=user))


@router.put("/{case_id}/documents/{type_code}/scan/pages/{page_no}", response_model=list[ScanPageOut])
async def retake_scan_page(
    case_id: int, type_code: str, page_no: int, request: Request,
    user: User = Depends(get_current_user), session: AsyncSession = Depends(get_session),
):
    """Take page `page_no` again: the new photo replaces it."""
    _photo_not_too_big(request)
    return _pages_out(await scanning.add_page(
        session, case_id=case_id, type_code=type_code, chunks=request.stream(), actor=user, replace=page_no
    ))


@router.get("/{case_id}/documents/{type_code}/scan/pages/{page_no}/image")
async def scan_page_image(
    case_id: int, type_code: str, page_no: int,
    user: User = Depends(get_current_user), session: AsyncSession = Depends(get_session),
):
    """The page as it will be in the PDF (upright, shrunk), for the preview."""
    content = await scanning.page_image(session, case_id, type_code, page_no, user)
    return Response(content, media_type="image/jpeg", headers={"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"})


@router.delete("/{case_id}/documents/{type_code}/scan/pages/{page_no}", response_model=list[ScanPageOut])
async def remove_scan_page(
    case_id: int, type_code: str, page_no: int,
    user: User = Depends(get_current_user), session: AsyncSession = Depends(get_session),
):
    return _pages_out(await scanning.remove_page(session, case_id, type_code, page_no, user))


@router.delete("/{case_id}/documents/{type_code}/scan", status_code=status.HTTP_204_NO_CONTENT)
async def cancel_scan(
    case_id: int, type_code: str, user: User = Depends(get_current_user), session: AsyncSession = Depends(get_session)
):
    await scanning.cancel(session, case_id, type_code, user)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{case_id}/documents/{type_code}/scan/finish", response_model=DocumentOut, status_code=status.HTTP_201_CREATED)
async def finish_scan(
    case_id: int, type_code: str, user: User = Depends(get_current_user), session: AsyncSession = Depends(get_session)
):
    """Join the pages into one PDF, stored as an upload of this document."""
    return _document_out(await scanning.finish(session, case_id=case_id, type_code=type_code, actor=user))


@router.post("/{case_id}/documents/{document_id}/original-seen", response_model=DocumentOut)
async def mark_original_seen(
    case_id: int,
    document_id: int,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """Records confirms they have seen the paper original of this upload, in person."""
    document = await service.mark_original_seen(
        session, case_id=case_id, document_id=document_id, actor=user
    )
    return _document_out(document)
