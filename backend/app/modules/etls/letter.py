"""The ETLS facility letter to GRA, as a PDF, issued once when it is signed.

When the PS (or someone acting for the PS) makes the "signed" move, the engine
runs the effect issue_letter() below, in the same transaction:
- build_fields() gathers what goes on the letter from the database;
- render_pdf() lays those fields out on the page, using the text template in
  templates/facility_letter.txt ($placeholders; a line wrapped in ** is bold;
  lines starting with ## are notes, one of them the template's version);
- the PDF is stored once (core/documents/issued.py) with its checksum and the
  template version. Downloads serve that stored file. It is never rendered again.

[CONFIRM] The wording of the letter, the Ministry's address line, and the
file reference format (settings.facility_letter_reference_format).
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
from app.core.config import settings
from app.core.documents import issued
from app.core.documents.models import IssuedDocument
from app.core.identity.models import Position, User
from app.core.workflow import effects
from app.core.workflow import service as workflow
from app.modules.etls.models import FacilityLetter
from app.modules.etls.service import FACILITY_LETTER

TEMPLATE = Path(__file__).parent / "templates" / "facility_letter.txt"
KIND = "etls_facility_letter"  # core.issued_documents.kind
ISSUE_EFFECT = "issue_facility_letter"  # core.transition_effects.effect_code
# The letter exists once the PS (or someone acting for them) has signed.
SIGNED_STATUSES = {"signed", "sent_to_gra", "closed"}


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
    signer_title: str
    acting_for: str  # e.g. "for the Permanent Secretary", or "" when the PS signed
    # Under "Sincerely,": the post whose signature it is, "For: ..." when someone
    # acted for it. [CONFIRM] Whether the acting officer's name and title should
    # also be printed (the Ministry's wording shows the title only).
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


def file_reference(case_id: int, year: int) -> str:
    # The format is checked at startup to use only {year} and {case_id}.
    return settings.facility_letter_reference_format.format(year=year, case_id=case_id)


def download_name(reference: str) -> str:
    return "facility-letter-" + re.sub(r"[^A-Za-z0-9-]+", "-", reference).strip("-") + ".pdf"


def _long_date(day: date) -> str:
    return f"{day.day} {day:%B %Y}"  # 19 October 2026


def _quantity(letter: FacilityLetter) -> str:
    # NUMERIC keeps trailing zeros (1200.500); a letter reads better without them.
    return format(letter.quantity.normalize(), "f")


def _hs_code(digits: str) -> str:
    # Stored as digits; printed the usual way: heading.subheading[.national].
    return ".".join([digits[:4], *(digits[i : i + 2] for i in range(4, len(digits), 2))]) if digits else ""


async def _position_title(session: AsyncSession, code: str) -> str:
    return await session.scalar(select(Position.title).where(Position.code == code)) or code


async def build_fields(session: AsyncSession, case_id: int, signing: AuditEvent) -> LetterFields:
    """The letter's fields. Who signed, and as what, comes from `signing`, the
    audit row of the "signed" move: the same record that shows whether they
    acted for the PS."""
    letter = await session.get(FacilityLetter, case_id)
    signer = await session.get(User, signing.actor_user_id)
    acting_for = signing.details.get("on_behalf_of")
    signed_on = signing.occurred_at.date()
    # Whose signature the letter carries: the post whose step it was.
    signing_post = await _position_title(session, acting_for or signing.details["as_position"])

    return LetterFields(
        file_reference=file_reference(case_id, signed_on.year),
        date=_long_date(signed_on),
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
        signer_name=signer.full_name,
        signer_title=await _position_title(session, signing.details["as_position"]),
        acting_for=f"for the {signing_post}" if acting_for else "",
        signature_title=f"For: {signing_post}" if acting_for else signing_post,
    )


def _latin1(text: str) -> str:
    # The built-in PDF fonts only cover Latin-1 (enough for English and French
    # names). Anything else becomes "?" rather than failing. A Unicode font
    # file would remove this limit.
    return text.encode("latin-1", "replace").decode("latin-1")


def render_pdf(fields: LetterFields, template: LetterTemplate | None = None, *, compress: bool = True) -> bytes:
    """Lay the letter out on an A4 page. compress=False keeps the text readable
    in the raw PDF bytes, which tests use to check what was printed."""
    template = template or load_template()
    values = asdict(fields)

    def fill(text: str) -> str:
        # substitute() (not safe_substitute) fails on a placeholder we don't fill,
        # so a typo in the template stops the signing instead of printing "$imprter".
        return _latin1(Template(text).substitute(values))

    pdf = FPDF(format="A4")
    pdf.set_compression(compress)
    pdf.set_title(f"ETLS facility letter {fields.file_reference}")
    pdf.set_margins(left=25, top=25, right=25)
    pdf.add_page()
    # The layout marks (** and " >> ") are read from the template line *before*
    # the fields are filled in, so an importer called "A >> B" can't move text.
    for line in template.body.splitlines():
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
    _, undo = await issued.issue(
        session,
        case=move.case,
        kind=KIND,
        content=render_pdf(fields, template),
        filename=download_name(fields.file_reference),
        template_version=template.version,
        template_sha256=template.sha256,
        actor=move.actor,
    )
    return undo


effects.register(ISSUE_EFFECT, issue_letter)


async def issued_letter(session: AsyncSession, case_id: int, user: User) -> tuple[IssuedDocument, bytes]:
    """The stored letter and its bytes (checked against the recorded checksum)."""
    case = await workflow.get_case(session, case_id, user)
    if not workflow.is_staff(user):
        # [CONFIRM] Whether the importer (who is copied) may download it here.
        raise workflow.NotPermitted("Only Ministry staff can download the facility letter.")
    if case.workflow.code != FACILITY_LETTER:
        raise workflow.NotFound("Facility letter not found.")
    document = await issued.get_issued(session, case.id, KIND)
    if document is None:
        if case.current_status.code in SIGNED_STATUSES:
            # Only cases signed before letters were stored (step 6f). We don't
            # make one now: that would be a letter nobody signed.
            raise workflow.NotFound("No issued letter is on file for this case.")
        raise workflow.NotReady("The facility letter isn't signed yet.")
    return document, issued.read(document)
