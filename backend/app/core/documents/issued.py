"""Documents the Ministry issues on a case (e.g. the signed facility letter).

An issued document is made once, at the moment it is issued, and stored with
its SHA-256 checksum and the version of the template it came from. From then on
the stored file is what everyone gets: it's never made again from the case's
data, so a later change to the data or the template can't change a letter the
PS already signed.

A mistake is corrected by cancelling the document (with a reason) and issuing
a new one, which records the one it replaces. The cancelled file is kept and
stays downloadable; a case has at most one *current* document of each kind.
"""

import logging

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit.service import record_event
from app.core.documents import storage
from app.core.documents.models import IssuedDocument
from app.core.identity.models import User
from app.core.workflow import service as workflow
from app.core.workflow.effects import Undo
from app.core.workflow.models import Case

logger = logging.getLogger(__name__)


async def all_issued(session: AsyncSession, case_id: int, kind: str) -> list[IssuedDocument]:
    """Every document of this kind on the case, oldest first, cancelled ones included."""
    return list(
        await session.scalars(
            select(IssuedDocument)
            .where(IssuedDocument.case_id == case_id, IssuedDocument.kind == kind)
            .order_by(IssuedDocument.issued_at, IssuedDocument.id)
        )
    )


async def get_current(session: AsyncSession, case_id: int, kind: str) -> IssuedDocument | None:
    """The one that hasn't been cancelled, if any."""
    return await session.scalar(
        select(IssuedDocument).where(
            IssuedDocument.case_id == case_id,
            IssuedDocument.kind == kind,
            IssuedDocument.cancelled_at.is_(None),
        )
    )


async def issue(
    session: AsyncSession,
    *,
    case: Case,
    kind: str,
    content: bytes,
    filename: str,
    template_version: str,
    template_sha256: str,
    actor: User,
    signature_note: str | None = None,
) -> tuple[IssuedDocument, Undo]:
    """Store `content` as the case's current `kind` and audit it. Does NOT commit.

    Returns the row and a function that deletes the file again, for the caller
    to use if the transaction fails (see workflow/effects.py).
    """
    earlier = await all_issued(session, case.id, kind)
    # A correction: the newest earlier one (always cancelled, or the unique
    # index below refuses a second current document).
    replaces = earlier[-1] if earlier else None
    stored = await storage.save_bytes(content)
    try:
        document = IssuedDocument(
            case_id=case.id,
            kind=kind,
            filename=filename,
            content_type=stored.content_type,
            size_bytes=stored.size_bytes,
            sha256=stored.sha256,
            storage_key=stored.storage_key,
            template_version=template_version,
            template_sha256=template_sha256,
            issued_by=actor.id,
            replaces_id=replaces.id if replaces else None,
            signature_note=signature_note,
        )
        session.add(document)
        # Flush now so a second current document of the same kind fails here,
        # on the unique index, rather than at commit.
        await session.flush()
        record_event(
            session,
            actor=actor,
            action="case.document_issued",
            entity_type=workflow.AUDIT_ENTITY,
            entity_id=case.id,
            details={
                "issued_document_id": document.id,
                "kind": kind,
                "sha256": stored.sha256,  # anyone can later prove the file is the one issued
                "size_bytes": stored.size_bytes,
                "template_version": template_version,
                "template_sha256": template_sha256,
                "replaces_issued_document_id": document.replaces_id,
                **({"signature_note": signature_note} if signature_note else {}),
            },
        )
    except BaseException:
        storage.delete(stored.storage_key)
        raise
    return document, lambda: storage.delete(stored.storage_key)


async def cancel(session: AsyncSession, *, document: IssuedDocument, actor: User, reason: str) -> None:
    """Mark the document cancelled and audit it. Does NOT commit. The file is kept."""
    document.cancelled_at = func.now()
    document.cancelled_by = actor.id
    document.cancellation_reason = reason
    await session.flush()
    # func.now() is only known after the flush; load it now, because async code
    # can't load it later on first touch.
    await session.refresh(document, ["cancelled_at"])
    record_event(
        session,
        actor=actor,
        action="case.document_cancelled",
        entity_type=workflow.AUDIT_ENTITY,
        entity_id=document.case_id,
        details={
            "issued_document_id": document.id,
            "kind": document.kind,
            "sha256": document.sha256,  # which file was cancelled
            "reason": reason,
        },
    )


def read(document: IssuedDocument) -> bytes:
    """The stored bytes, checked against the recorded checksum.

    A mismatch means the file was changed or damaged on disk. That's served as
    an error (500), never as the letter, and logged for the administrator.
    """
    try:
        return storage.read_verified(document.storage_key, document.sha256)
    except storage.StoredFileChanged:
        logger.error("Issued document %s (case %s) fails its checksum", document.id, document.case_id)
        raise
