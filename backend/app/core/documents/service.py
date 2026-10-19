"""Documents on cases: what a case needs, uploads, and downloads.

Requirements are data (core.document_requirements). A conditional one is tested
against the facts its module supplies (facts.py), e.g. "a receipt when the
product is cement".
"""

import re
from collections.abc import AsyncIterator
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit.service import record_event
from app.core.documents import facts, storage
from app.core.documents.conditions import holds
from app.core.documents.models import CaseDocument, DocumentRequirement
from app.core.identity.models import User
from app.core.workflow import service as workflow
from app.core.workflow.errors import InvalidDocument, NotFound
from app.core.workflow.models import Case

_UNSAFE = re.compile(r"[^A-Za-z0-9._ -]")


@dataclass
class RequirementStatus:
    requirement: DocumentRequirement
    applies: bool  # False when its condition doesn't hold for this case
    documents: list[CaseDocument]  # uploads of this type, newest first

    @property
    def missing(self) -> bool:
        return self.applies and not self.documents


def clean_filename(name: str | None, fallback: str) -> str:
    """A display name that is safe in a header and a file dialog."""
    name = (name or "").replace("\\", "/").rsplit("/", 1)[-1]  # drop any folder part
    name = _UNSAFE.sub("_", name).strip(" .")[:100]
    return name or fallback


async def checklist(session: AsyncSession, case: Case) -> list[RequirementStatus]:
    """Every document type this case's workflow takes, whether it applies, and what's uploaded."""
    requirements = (
        await session.scalars(
            select(DocumentRequirement)
            .where(DocumentRequirement.workflow_id == case.workflow_id)
            .order_by(DocumentRequirement.id)
        )
    ).all()
    case_facts = await facts.facts_for(session, case.workflow.code, case.id)
    uploads = (
        await session.scalars(
            select(CaseDocument)
            .where(CaseDocument.case_id == case.id)
            .order_by(CaseDocument.uploaded_at.desc(), CaseDocument.id.desc())
        )
    ).all()
    return [
        RequirementStatus(
            requirement=r,
            applies=holds(r.condition, case_facts),
            documents=[d for d in uploads if d.document_type_id == r.document_type_id],
        )
        for r in requirements
    ]


async def missing_documents(session: AsyncSession, case: Case) -> list[str]:
    """Names of required documents not uploaded yet."""
    return [s.requirement.document_type.name for s in await checklist(session, case) if s.missing]


async def upload(
    session: AsyncSession,
    *,
    case_id: int,
    type_code: str,
    filename: str | None,
    chunks: AsyncIterator[bytes],
    actor: User,
) -> CaseDocument:
    # Only someone who can see the case may add to it: the applicant who opened
    # it, or staff. get_case() gives everyone else a 404.
    case = await workflow.get_case(session, case_id, actor)
    if case.current_status.is_final:
        raise InvalidDocument("This case is closed; no more documents can be added.")
    statuses = await checklist(session, case)
    requirement = next(
        (s.requirement for s in statuses if s.requirement.document_type.code == type_code), None
    )
    if requirement is None:
        raise InvalidDocument(f"This kind of case doesn't take a '{type_code}' document.")

    stored = await storage.save(chunks)
    try:
        document = CaseDocument(
            case_id=case.id,
            document_type_id=requirement.document_type_id,
            filename=clean_filename(filename, type_code),
            content_type=stored.content_type,
            size_bytes=stored.size_bytes,
            sha256=stored.sha256,
            storage_key=stored.storage_key,
            uploaded_by=actor.id,
        )
        session.add(document)
        await session.flush()
        record_event(
            session,
            actor=actor,
            action="case.document_uploaded",
            entity_type=workflow.AUDIT_ENTITY,
            entity_id=case.id,
            details={
                "document_id": document.id,
                "type": type_code,
                "filename": document.filename,
                "size_bytes": stored.size_bytes,
                "sha256": stored.sha256,
            },
        )
        await session.commit()
    except BaseException:
        # Don't leave a file on disk that no row points to.
        storage.delete(stored.storage_key)
        raise
    # A new object's relationships aren't loaded, and async code can't load them
    # on first touch (see create_user()).
    await session.refresh(document, ["document_type"])
    return document


async def get_document(
    session: AsyncSession, *, case_id: int, document_id: int, user: User
) -> CaseDocument:
    case = await workflow.get_case(session, case_id, user)
    document = await session.get(CaseDocument, document_id)
    if document is None or document.case_id != case.id:
        raise NotFound("Document not found.")
    return document
