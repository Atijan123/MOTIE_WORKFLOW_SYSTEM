"""Documents on cases: what a case needs, uploads, and downloads.

Requirements are data (core.document_requirements). A conditional one is tested
against the facts its module supplies (facts.py), e.g. "a receipt when the
HS heading is 2523 (cement)".
"""

import re
from collections.abc import AsyncIterator
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit.service import record_event
from app.core.documents import facts, storage
from app.core.documents.conditions import holds
from app.core.documents.models import CaseDocument, DocumentRequirement
from app.core.identity.models import User
from app.core.workflow import checks
from app.core.workflow import service as workflow
from app.core.workflow.errors import InvalidDocument, NotFound, NotPermitted
from app.core.workflow.models import Case

_UNSAFE = re.compile(r"[^A-Za-z0-9._ -]")

# Transition check names this service provides (see core/workflow/checks.py).
DOCUMENTS_COMPLETE = "documents_complete"  # strict: nothing missing, nothing undecided
KNOWN_DOCUMENTS_COMPLETE = "known_documents_complete"  # lenient: undecided ones wait
ORIGINALS_SEEN = "originals_seen"


@dataclass
class RequirementStatus:
    requirement: DocumentRequirement
    # False when its condition doesn't hold for this case; None when that can't
    # be told yet, because a fact it depends on has no value yet.
    applies: bool | None
    documents: list[CaseDocument]  # uploads of this type, newest first

    @property
    def missing(self) -> bool:
        return self.applies is True and not self.documents

    @property
    def undecided(self) -> bool:
        return self.applies is None

    @property
    def original_pending(self) -> bool:
        """The paper original must be seen, and the newest upload hasn't been.
        A re-upload after the original was seen must be checked again."""
        if not (self.applies is True and self.requirement.original_required):
            return False
        return not self.documents or self.documents[0].original_seen_at is None


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


async def mark_original_seen(
    session: AsyncSession, *, case_id: int, document_id: int, actor: User
) -> CaseDocument:
    """Record that `actor` has seen the paper original of this upload, in person.

    Allowed for whoever may make the move that requires it (Records on a
    facility letter, or someone acting for Records), and only for documents
    whose original is required. Marking twice changes nothing.
    """
    document = await get_document(session, case_id=case_id, document_id=document_id, user=actor)
    case = await workflow.get_case(session, case_id, actor, for_update=True)
    requirement = await session.scalar(
        select(DocumentRequirement).where(
            DocumentRequirement.workflow_id == case.workflow_id,
            DocumentRequirement.document_type_id == document.document_type_id,
        )
    )
    if requirement is None or not requirement.original_required:
        raise InvalidDocument("This document's original doesn't need to be seen.")
    if not await workflow.may_make_move_with_check(session, case, actor, ORIGINALS_SEEN):
        raise NotPermitted("Only the officer receiving the originals can mark them as seen.")
    if document.original_seen_at is not None:
        return document

    document.original_seen_at = func.now()
    document.original_seen_by = actor.id
    record_event(
        session,
        actor=actor,
        action="case.original_seen",
        entity_type=workflow.AUDIT_ENTITY,
        entity_id=case.id,
        details={
            "document_id": document.id,
            "type": document.document_type.code,
            "sha256": document.sha256,  # which scan the original was compared with
        },
    )
    await session.commit()
    await session.refresh(document, ["original_seen_at"])
    return document


async def _check_documents_complete(session: AsyncSession, case: Case) -> list[str]:
    problems = []
    for s in await checklist(session, case):
        name = s.requirement.document_type.name
        if s.missing:
            problems.append(f"{name} is missing")
        elif s.undecided and not s.documents:
            # Can't tell yet whether it's needed: treat that as not ready.
            problems.append(f"it isn't known yet whether {name.lower()} is needed")
    return problems


async def _check_known_documents_complete(session: AsyncSession, case: Case) -> list[str]:
    """Every document known to be needed is in. Ones that can't be decided yet
    are left for a later, strict documents_complete check."""
    return [f"{name} is missing" for name in await missing_documents(session, case)]


async def _check_originals_seen(session: AsyncSession, case: Case) -> list[str]:
    return [
        f"the original {s.requirement.document_type.name.lower()} hasn't been marked as seen"
        for s in await checklist(session, case)
        if s.original_pending
    ]


checks.register(DOCUMENTS_COMPLETE, _check_documents_complete)
checks.register(KNOWN_DOCUMENTS_COMPLETE, _check_known_documents_complete)
checks.register(ORIGINALS_SEEN, _check_originals_seen)
