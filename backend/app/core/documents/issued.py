"""Documents the Ministry issues on a case (e.g. the signed facility letter).

An issued document is made once, at the moment it is issued, and stored with
its SHA-256 checksum and the version of the template it came from. From then on
the stored file is what everyone gets: it's never made again from the case's
data, so a later change to the data or the template can't change a letter the
PS already signed.
"""

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit.service import record_event
from app.core.documents import storage
from app.core.documents.models import IssuedDocument
from app.core.identity.models import User
from app.core.workflow import service as workflow
from app.core.workflow.effects import Undo
from app.core.workflow.models import Case

logger = logging.getLogger(__name__)


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
) -> tuple[IssuedDocument, Undo]:
    """Store `content` as the case's issued `kind` and audit it. Does NOT commit.

    Returns the row and a function that deletes the file again, for the caller
    to use if the transaction fails (see workflow/effects.py).
    """
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
        )
        session.add(document)
        # Flush now so a second issue of the same kind fails here, on the
        # unique constraint, rather than at commit.
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
            },
        )
    except BaseException:
        storage.delete(stored.storage_key)
        raise
    return document, lambda: storage.delete(stored.storage_key)


async def get_issued(session: AsyncSession, case_id: int, kind: str) -> IssuedDocument | None:
    return await session.scalar(
        select(IssuedDocument).where(IssuedDocument.case_id == case_id, IssuedDocument.kind == kind)
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
