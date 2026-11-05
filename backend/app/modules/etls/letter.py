"""The ETLS facility letter to GRA, as a PDF, issued once when it is signed.

Who signs (SCREENS.md S3): the Director of Industry and Investment, "For:
Permanent Secretary", or while every Director is recorded absent, an
authorised signatory from the Director's office's list (S12). That's the
"signed" move's row and core.signatory_rules (migrations 0040, 0041), not code
here. When one of them makes the move, the engine runs the effect
issue_letter() below, in the same transaction:
- build_fields() gathers what goes on the letter from the database;
- render_pdf() lays those fields out on the page, using the text template in
  templates/facility_letter.txt ($placeholders; a line wrapped in ** is bold;
  a line of fields that are all empty is left out; lines starting with ## are
  notes, one of them the template's version);
- the PDF is stored once (core/documents/issued.py) with its checksum, the
  template version and why the signer could sign ("in the Director's
  absence"), and three copies of it are recorded (etls.facility_letter_copies):
  Records' file copy, GRA's, and the applicant's. Downloads serve that stored
  file. It is never rendered again.

To correct a signed letter, the Director (or the officer who signed that
letter, while still acting for the Director) makes the move "Cancel the
signed letter" with a reason; its effect cancel_letter() marks the letter
cancelled (the file is kept). The case goes back to the desk, and the next
signing issues a corrected letter that records the one it replaces.

[CONFIRM] The wording of the letter, the Ministry's address line, and the
registry file reference (settings.facility_letter_reference_format).
"""

import hashlib
import re
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path
from string import Template

from fpdf import FPDF
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit.models import AuditEvent
from app.core.audit.service import record_event
from app.core.config import settings
from app.core.dates import long_date  # noqa: F401  (also used as letter.long_date)
from app.core.documents import issued
from app.core.documents.models import IssuedDocument
from app.core.identity.models import Position, User
from app.core.workflow import checks, effects
from app.core.workflow import service as workflow
from app.core.workflow.delegation import today
from app.core.workflow.models import Case
from app.modules.etls.models import FacilityLetter, FacilityLetterCopy, FacilityLetterDispatch
from app.modules.etls.service import FACILITY_LETTER, form_gaps

TEMPLATE = Path(__file__).parent / "templates" / "facility_letter.txt"
KIND = "etls_facility_letter"  # core.issued_documents.kind
ISSUE_EFFECT = "issue_facility_letter"  # core.transition_effects.effect_code
CANCEL_EFFECT = "cancel_facility_letter"
DISPATCH_RECORDED = "etls_dispatch_recorded"  # check on "Mark sent to GRA"
REFERENCE_SET = "etls_registry_reference_set"  # check on "Sign"
REFERENCE_NOT_SET = (
    "the Ministry's registry file reference isn't set on this server "
    "(FACILITY_LETTER_REFERENCE_FORMAT); ask the system administrator"
)
# Signing records these copies of the one stored letter (0041), in this order.
# GRA's is the one Records dispatches; the applicant's can be downloaded once
# GRA's is sent. [CONFIRM] How the applicant collects a paper copy.
COPIES = {"records_file": "Records' file copy", "gra": "GRA's copy", "applicant": "The applicant's copy"}
# The letter exists once it has been signed.
SIGNED_STATUSES = {"signed", "sent_to_gra"}


@dataclass
class LetterFields:
    file_reference: str
    date: str
    importer_name: str
    importer_name_upper: str  # for the subject line, which is in capitals
    importer_address: str
    product: str
    hs_code: str  # as confirmed by the officer, e.g. 2523.29
    quantity: str  # the number only, e.g. 1200.5
    unit: str
    exporter_name: str
    exporter_country: str
    exporter_approval_number: str
    product_approval_numbers: str
    certificate_numbers: str
    signer_name: str
    signer_title: str  # their post, or "Authorised signatory"
    acting_for: str  # e.g. "for the Director of Industry and Investment", or "" when the post holder signed
    # The signature block under "Sincerely,", as the Ministry's letters have it:
    #   [signer's name]
    #   For: Permanent Secretary
    # Why a signatory could sign ("in the Director's absence") isn't printed; it's
    # kept with the stored letter and in the audit log. A preview for someone
    # who may not sign has no name, and the empty line is left out.
    signature_name: str
    signature_title: str


@dataclass(frozen=True)
class LetterTemplate:
    body: str  # the text to fill in, without the ## notes
    version: str  # from the "## version:" line
    sha256: str  # of the whole file, so even an unlabelled edit is visible


def load_template(path: Path | None = None) -> LetterTemplate:
    raw = (path or TEMPLATE).read_bytes()
    version, body = None, []
    for line in raw.decode("utf-8").splitlines():
        if line.startswith("##"):
            note = line[2:].strip()
            if note.lower().startswith("version:"):
                version = note.split(":", 1)[1].strip()
            continue
        body.append(line)
    if not version:
        # Every issued letter records its template version, so refuse to issue without one.
        raise ValueError(f"{path or TEMPLATE} has no '## version: ...' line")
    return LetterTemplate("\n".join(body), version, hashlib.sha256(raw).hexdigest())


def file_reference(case_id: int, year: int, *, preview: bool = False) -> str:
    # The format is checked at startup to use only {year} and {case_id}.
    reference = settings.registry_reference_format()
    if reference is None:
        if preview:
            return "[REGISTRY FILE REFERENCE NOT SET]"
        # The Sign move's check stops this first; this is the last guard.
        raise workflow.NotReady("Not ready: " + REFERENCE_NOT_SET)
    return reference.format(year=year, case_id=case_id)


def download_name(reference: str, number: int = 1) -> str:
    """facility-letter-MOTIE-ETLS-FL-2026-0042.pdf, from the case reference
    (the registry reference is the same on every letter); a correction ends -2, -3, ..."""
    name = "facility-letter-" + re.sub(r"[^A-Za-z0-9-]+", "-", reference).strip("-")
    return f"{name}-{number}.pdf" if number > 1 else f"{name}.pdf"


def _quantity(letter: FacilityLetter) -> str:
    # NUMERIC keeps trailing zeros (1200.500); a letter reads better without them.
    return format(letter.quantity.normalize(), "f")


def _hs_code(digits: str) -> str:
    # Stored as digits; printed the usual way: heading.subheading[.national].
    return ".".join([digits[:4], *(digits[i : i + 2] for i in range(4, len(digits), 2))]) if digits else ""


async def _position_title(session: AsyncSession, code: str) -> str:
    return await session.scalar(select(Position.title).where(Position.code == code)) or code


def _form_fields(letter: FacilityLetter) -> dict:
    """The fields that come from the application itself."""
    return dict(
        importer_name=letter.importer_name,
        importer_name_upper=letter.importer_name.upper(),
        importer_address=letter.importer_address,
        product=letter.product,
        hs_code=_hs_code(letter.hs_code_confirmed or letter.hs_code or ""),
        quantity=_quantity(letter),
        unit=letter.unit,
        exporter_name=letter.exporter_name,
        exporter_country=letter.exporter_country,
        exporter_approval_number=letter.exporter_etls_approval_number,
        product_approval_numbers=", ".join(a.number for a in letter.product_approvals),
        certificate_numbers=", ".join(c.number for c in letter.certificates),
    )


SIGNATORY_TITLE = "Authorised signatory"
# Every facility letter is the PS's letter: the Director signs it "For:
# Permanent Secretary" (SCREENS.md S3), as does anyone acting for the Director.
LETTER_FROM = "permanent_secretary"


async def _signature(session: AsyncSession, name: str) -> dict:
    return dict(signature_name=name, signature_title=f"For: {await _position_title(session, LETTER_FROM)}")


async def build_fields(session: AsyncSession, case_id: int, signing: AuditEvent) -> LetterFields:
    """The letter's fields. Who signed, and as what, comes from `signing`, the
    audit row of the "signed" move: the same record that shows whether they
    acted for the post, and on what basis."""
    letter = await session.get(FacilityLetter, case_id)
    signer = await session.get(User, signing.actor_user_id)
    details = signing.details
    acting_for = details.get("on_behalf_of")
    signed_on = signing.occurred_at.date()
    # An authorised signatory signs as a named person, from no post.
    signatory = details.get("basis") == "signatory"

    return LetterFields(
        file_reference=file_reference(case_id, signed_on.year),
        date=long_date(signed_on),
        **_form_fields(letter),
        signer_name=signer.full_name,
        signer_title=SIGNATORY_TITLE if signatory else await _position_title(session, details["as_position"]),
        acting_for=f"for the {await _position_title(session, acting_for)}" if acting_for else "",
        # A signatory's name as recorded at signing, so a later change of name doesn't change the letter.
        **await _signature(session, details.get("signatory_name") or signer.full_name),
    )


async def preview_fields(session: AsyncSession, case: Case, user: User) -> LetterFields:
    """The letter as it would read if `user` signed it today: with their name
    if they may sign it, with no name otherwise."""
    letter = await session.get(FacilityLetter, case.id)
    mine = next(
        (m for m in await workflow.available_transitions(session, case, user) if m.transition.to_status.code == "signed"),
        None,
    )
    post = mine.transition.required_position.title if mine else ""
    return LetterFields(
        file_reference=file_reference(case.id, today().year, preview=True),
        date=long_date(today()),
        **_form_fields(letter),
        signer_name=user.full_name if mine else "",
        signer_title=(SIGNATORY_TITLE if mine.signatory else post) if mine else "",
        acting_for=f"for the {post}" if mine and mine.on_behalf_of else "",
        **await _signature(session, user.full_name if mine else ""),
    )


def _latin1(text: str) -> str:
    # The built-in PDF fonts only cover Latin-1 (enough for English and French
    # names). Anything else becomes "?" rather than failing. A Unicode font
    # file would remove this limit.
    return text.encode("latin-1", "replace").decode("latin-1")


PREVIEW_MARK = "DRAFT FOR CHECKING - NOT SIGNED - NOT VALID AS A FACILITY LETTER"
_FIELDS_ONLY = re.compile(r"(\s*\$\w+)+\s*")


def render_pdf(
    fields: LetterFields,
    template: LetterTemplate | None = None,
    *,
    issue: int = 1,
    compress: bool = True,
    preview: bool = False,
) -> bytes:
    """Lay the letter out on an A4 page. compress=False keeps the text readable
    in the raw PDF bytes, which tests use to check what was printed. A
    preview carries PREVIEW_MARK at the top, so a printout can't pass for
    the real letter."""
    template = template or load_template()
    values = asdict(fields)

    def fill(text: str) -> str:
        # substitute() (not safe_substitute) fails on a placeholder we don't fill,
        # so a typo in the template stops the signing instead of printing "$imprter".
        return _latin1(Template(text).substitute(values))

    pdf = FPDF(format="A4")
    pdf.set_compression(compress)
    pdf.set_title(f"ETLS facility letter {fields.file_reference}")
    # Which issue this is (2 = the first correction). Not printed, but part of
    # the file, so a correction never has the same checksum as the letter it
    # replaces, even when nothing printed changed.
    pdf.set_subject("Preview, not issued" if preview else f"Issue {issue}")
    pdf.set_margins(left=25, top=25, right=25)
    pdf.add_page()
    if preview:
        pdf.set_font("Helvetica", style="B", size=12)
        pdf.set_text_color(200, 0, 0)
        pdf.multi_cell(w=0, h=8, text=PREVIEW_MARK, align="C", border=1, new_x="LMARGIN", new_y="NEXT")
        pdf.set_text_color(0, 0, 0)
        pdf.ln(4)
    # The layout marks (** and " >> ") are read from the template line *before*
    # the fields are filled in, so an importer called "A >> B" can't move text.
    for line in template.body.splitlines():
        # A line made only of fields, all of them empty (e.g. no signatory's
        # name), is left out rather than printed as a gap.
        if _FIELDS_ONLY.fullmatch(line) and not fill(line).strip():
            continue
        bold = line.startswith("**") and line.endswith("**") and len(line) > 4
        pdf.set_font("Helvetica", style="B" if bold else "", size=11)
        line = line[2:-2] if bold else line
        if " >> " in line:
            left, right = line.split(" >> ", 1)
            pdf.cell(w=pdf.epw / 2, h=6, text=fill(left))
            pdf.cell(w=0, h=6, text=fill(right), align="R", new_x="LMARGIN", new_y="NEXT")
        else:
            # multi_cell wraps long lines inside the margins; an empty line is a gap.
            pdf.multi_cell(w=0, h=6, text=fill(line) or " ", new_x="LMARGIN", new_y="NEXT")
    return bytes(pdf.output())


async def issue_letter(session: AsyncSession, move: effects.Move) -> effects.Undo:
    """The effect of the "signed" move: render the letter once and store it."""
    await session.flush()  # gives the signing audit row its time, which dates the letter
    fields = await build_fields(session, move.case.id, move.event)
    template = load_template()
    # [CONFIRM] A corrected letter keeps the same file reference, with a new date.
    number = len(await issued.all_issued(session, move.case.id, KIND)) + 1
    document, undo = await issued.issue(
        session,
        case=move.case,
        kind=KIND,
        content=render_pdf(fields, template, issue=number),
        filename=download_name(move.case.reference, number),
        template_version=template.version,
        template_sha256=template.sha256,
        actor=move.actor,
        # Not printed (template version 4), but kept with the letter.
        signature_note=move.event.details.get("in_absence"),
    )
    # One stored file, three copies of it to account for.
    for recipient in COPIES:
        session.add(FacilityLetterCopy(case_id=move.case.id, issued_document_id=document.id, recipient=recipient))
    return undo


async def cancel_letter(session: AsyncSession, move: effects.Move) -> None:
    """The effect of "Cancel the signed letter": the current letter is marked
    cancelled, with the move's comment as the reason. Its file is kept."""
    current = await issued.get_current(session, move.case.id, KIND)
    if current is None:
        # Only a case signed before letters were stored (step 6f) gets here.
        raise workflow.NotReady("There is no issued letter on file to cancel.")
    # The engine has already made sure the move has a reason (requires_comment).
    await issued.cancel(session, document=current, actor=move.actor, reason=move.event.details["comment"])


async def mark_sent_to_gra(session: AsyncSession, *, case_id: int, actor: User, dispatched_on: date) -> Case:
    """Records sends the signed letter to GRA (SCREENS.md S1, "Outgoing"):
    the dispatch date is recorded against the exact letter sent, and the case
    moves to "Sent to GRA", in one transaction.

    Who may do it is the move's own rule (the Records post, or someone acting
    for it), checked by change_status(). The generic POST /cases/{id}/status
    can't make the move without a date: its check etls_dispatch_recorded
    finds no dispatch for the current letter.
    """
    case = await _staff_case(session, case_id, actor)
    # Asked first, with the engine's own rules, so a refusal never leaves a
    # half-recorded dispatch in the session.
    send = next(
        (m for m in await workflow.available_transitions(session, case, actor) if m.transition.to_status.code == "sent_to_gra"),
        None,
    )
    if send is None:
        raise workflow.NotPermitted("Only Records (or someone acting for Records) sends signed letters to GRA.")
    if blocked := await workflow.what_blocks(session, case, send.transition):
        raise workflow.NotReady("Not ready: " + "; ".join(blocked))
    current = await issued.get_current(session, case.id, KIND)
    if current is None:
        raise workflow.NotReady("There is no signed letter on file to send.")
    if dispatched_on > today():
        raise workflow.InvalidDate("The dispatch date can't be in the future.")
    if dispatched_on < current.issued_at.date():
        raise workflow.InvalidDate("The letter can't have been sent before it was signed.")

    session.add(
        FacilityLetterDispatch(
            case_id=case.id, issued_document_id=current.id, dispatched_on=dispatched_on, recorded_by=actor.id
        )
    )
    record_event(
        session,
        actor=actor,
        action="case.letter_dispatched",
        entity_type=workflow.AUDIT_ENTITY,
        entity_id=case.id,
        details={
            "issued_document_id": current.id,
            "sha256": current.sha256,  # which file went to GRA
            "dispatched_on": dispatched_on.isoformat(),
        },
    )
    try:
        # Commits the dispatch, its audit row and the move together.
        return await workflow.change_status(session, case_id=case.id, to_status_code="sent_to_gra", actor=actor)
    except BaseException:
        # Only something unexpected gets here (e.g. another officer moved the
        # case at the same moment). The dispatch row mustn't stay in this
        # session for a later commit to save.
        await session.rollback()
        raise


async def preview(session: AsyncSession, case_id: int, user: User) -> bytes:
    """The letter as it would be signed now, for the signer to read before
    signing (SCREENS.md S3). Made fresh on each request and never stored: only the
    signing move issues a letter."""
    case = await _staff_case(session, case_id, user)
    if await issued.get_current(session, case.id, KIND):
        raise workflow.NotReady("The letter is signed; download it from letter.pdf.")
    gaps = form_gaps(await session.get(FacilityLetter, case.id))
    if gaps:
        # Only a draft can have gaps; there's no letter to show yet.
        raise workflow.NotReady("The application form isn't complete: " + "; ".join(gaps))
    return render_pdf(await preview_fields(session, case, user), preview=True)


async def _check_registry_reference_set(session: AsyncSession, case: Case) -> list[str]:
    """Blocks Sign on a server whose registry reference was never set: a
    letter must not go out with the developers' example reference."""
    return [] if settings.registry_reference_format() else [REFERENCE_NOT_SET]


async def _check_dispatch_recorded(session: AsyncSession, case: Case) -> list[str]:
    current = await issued.get_current(session, case.id, KIND)
    if current is not None and await session.scalar(
        select(FacilityLetterDispatch.id).where(FacilityLetterDispatch.issued_document_id == current.id)
    ):
        return []
    return ["the dispatch date hasn't been entered; use Mark sent to GRA with the date"]


async def dispatches(session: AsyncSession, case_id: int) -> dict[int, FacilityLetterDispatch]:
    """{issued letter id: its dispatch}, for the letters listing."""
    rows = await session.scalars(select(FacilityLetterDispatch).where(FacilityLetterDispatch.case_id == case_id))
    return {d.issued_document_id: d for d in rows}


effects.register(ISSUE_EFFECT, issue_letter)
effects.register(CANCEL_EFFECT, cancel_letter)
checks.register(DISPATCH_RECORDED, _check_dispatch_recorded)
checks.register(REFERENCE_SET, _check_registry_reference_set)


async def _staff_case(session: AsyncSession, case_id: int, user: User):
    case = await workflow.get_case(session, case_id, user)
    if not workflow.is_staff(user):
        # [CONFIRM] Whether the importer (who is copied) may download it here.
        raise workflow.NotPermitted("Only Ministry staff can download the facility letter.")
    if case.workflow.code != FACILITY_LETTER:
        raise workflow.NotFound("Facility letter not found.")
    return case


async def letters(session: AsyncSession, case_id: int, user: User) -> list[IssuedDocument]:
    """Every letter issued on the case, oldest first, cancelled ones included."""
    case = await _staff_case(session, case_id, user)
    return await issued.all_issued(session, case.id, KIND)


async def current_letter(session: AsyncSession, case_id: int, user: User) -> tuple[IssuedDocument, bytes]:
    """The letter in force and its bytes (checked against the recorded checksum)."""
    case = await _staff_case(session, case_id, user)
    document = await issued.get_current(session, case.id, KIND)
    if document is None:
        if await issued.all_issued(session, case.id, KIND):
            raise workflow.NotReady("The letter was cancelled and a corrected one hasn't been signed yet.")
        if case.current_status.code in SIGNED_STATUSES:
            # Only cases signed before letters were stored (step 6f). We don't
            # make one now: that would be a letter nobody signed.
            raise workflow.NotFound("No issued letter is on file for this case.")
        raise workflow.NotReady("The facility letter isn't signed yet.")
    return document, issued.read(document)


async def letter_by_id(
    session: AsyncSession, case_id: int, letter_id: int, user: User
) -> tuple[IssuedDocument, bytes]:
    """Any one of the case's letters, current or cancelled."""
    document = next((d for d in await letters(session, case_id, user) if d.id == letter_id), None)
    if document is None:
        raise workflow.NotFound("Letter not found.")
    return document, issued.read(document)


async def copies(session: AsyncSession, case_id: int) -> dict[int, list[FacilityLetterCopy]]:
    """{issued letter id: its copies, in COPIES order}, for the letters listing."""
    order = list(COPIES)
    found: dict[int, list[FacilityLetterCopy]] = {}
    for c in await session.scalars(select(FacilityLetterCopy).where(FacilityLetterCopy.case_id == case_id)):
        found.setdefault(c.issued_document_id, []).append(c)
    return {k: sorted(v, key=lambda c: order.index(c.recipient)) for k, v in found.items()}


async def applicant_copy_ready(session: AsyncSession, case: Case) -> IssuedDocument | None:
    """The letter in force, if its GRA copy has been sent: the applicant's copy
    may then be downloaded. None before that, or while a corrected letter is awaited."""
    current = await issued.get_current(session, case.id, KIND)
    if current is None:
        return None
    sent = await session.scalar(
        select(FacilityLetterDispatch.id).where(FacilityLetterDispatch.issued_document_id == current.id)
    )
    return current if sent else None


async def applicant_copy(session: AsyncSession, case_id: int, user: User) -> tuple[IssuedDocument, bytes]:
    """The applicant's copy of the letter in force (SCREENS.md S3, A3), for the
    applicant (or Records, for a walk-in), once GRA's copy is marked sent."""
    case = await workflow.get_case(session, case_id, user)
    if case.workflow.code != FACILITY_LETTER or not workflow.acts_as_applicant(case, user):
        raise workflow.NotFound("Facility letter not found.")
    document = await applicant_copy_ready(session, case)
    if document is None:
        raise workflow.NotReady("Your copy of the letter is available once the Ministry has sent the letter to GRA.")
    return document, issued.read(document)

