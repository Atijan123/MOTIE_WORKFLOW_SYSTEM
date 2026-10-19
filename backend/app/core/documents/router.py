from datetime import datetime

from fastapi import APIRouter, Depends, Request, status
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.documents import service, storage
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
    applies: bool  # False when a condition (e.g. "product is cement") doesn't hold
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
