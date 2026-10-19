"""The ETLS facility letter to GRA, as a PDF.

Two halves, tested separately:
- letter_fields() gathers what goes on the letter from the database;
- render_pdf() lays those fields out on the page, using the text template in
  templates/facility_letter.txt ($placeholders; a line wrapped in ** is bold).

[CONFIRM] The wording of the letter, the Ministry's address line, and the
file reference format (settings.facility_letter_reference_format).
"""

from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path
from string import Template

from fpdf import FPDF
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit.models import AuditEvent
from app.core.config import settings
from app.core.identity.models import Position, User
from app.core.workflow import service as workflow
from app.modules.etls.models import FacilityLetter

TEMPLATE = Path(__file__).parent / "templates" / "facility_letter.txt"
# The letter exists once the PS (or someone acting for them) has signed.
SIGNED_STATUSES = {"signed", "sent_to_gra", "closed"}


@dataclass
class LetterFields:
    file_reference: str
    date: str
    importer_name: str
    importer_address: str
    product: str
    quantity: str
    exporter_name: str
    exporter_country: str
    exporter_approval_number: str
    product_approval_numbers: str
    certificate_numbers: str
    signer_name: str
    signer_title: str
    acting_for: str  # e.g. "for the Permanent Secretary", or "" when the PS signed


def file_reference(case_id: int, year: int) -> str:
    # The format is checked at startup to use only {year} and {case_id}.
    return settings.facility_letter_reference_format.format(year=year, case_id=case_id)


def _long_date(day: date) -> str:
    return f"{day.day} {day:%B %Y}"  # 19 October 2026


def _quantity(letter: FacilityLetter) -> str:
    # NUMERIC keeps trailing zeros (1200.500); a letter reads better without them.
    amount = format(letter.quantity.normalize(), "f")
    return f"{amount} {letter.unit}"


async def _position_title(session: AsyncSession, code: str) -> str:
    return await session.scalar(select(Position.title).where(Position.code == code)) or code


async def letter_fields(session: AsyncSession, case_id: int, user: User) -> LetterFields:
    case = await workflow.get_case(session, case_id, user)
    if not workflow.is_staff(user):
        # [CONFIRM] Whether the importer (who is copied) may download it here.
        raise workflow.NotPermitted("Only Ministry staff can download the facility letter.")
    letter = await session.get(FacilityLetter, case.id)
    if letter is None:
        raise workflow.NotFound("Facility letter not found.")
    if case.current_status.code not in SIGNED_STATUSES:
        raise workflow.NotReady("The facility letter isn't signed yet.")

    # Who signed, and as what, comes from the audit row of the "signed" move:
    # the same record that shows whether they acted for the PS.
    signing = await session.scalar(
        select(AuditEvent)
        .where(
            AuditEvent.entity_type == workflow.AUDIT_ENTITY,
            AuditEvent.entity_id == str(case.id),
            AuditEvent.action == "case.status_changed",
            AuditEvent.details["to"].astext == "signed",
        )
        .order_by(AuditEvent.occurred_at.desc(), AuditEvent.id.desc())
        .limit(1)
    )
    signer = await session.get(User, signing.actor_user_id)
    acting_for = signing.details.get("on_behalf_of")
    signed_on = signing.occurred_at.date()

    return LetterFields(
        file_reference=file_reference(case.id, signed_on.year),
        date=_long_date(signed_on),
        importer_name=letter.importer_name,
        importer_address=letter.importer_address,
        product=letter.product,
        quantity=_quantity(letter),
        exporter_name=letter.exporter_name,
        exporter_country=letter.exporter_country,
        exporter_approval_number=letter.exporter_etls_approval_number,
        product_approval_numbers=", ".join(a.number for a in letter.product_approvals),
        certificate_numbers=", ".join(c.number for c in letter.certificates),
        signer_name=signer.full_name,
        signer_title=await _position_title(session, signing.details["as_position"]),
        acting_for=f"for the {await _position_title(session, acting_for)}" if acting_for else "",
    )


def _latin1(text: str) -> str:
    # The built-in PDF fonts only cover Latin-1 (enough for English and French
    # names). Anything else becomes "?" rather than failing. A Unicode font
    # file would remove this limit.
    return text.encode("latin-1", "replace").decode("latin-1")


def render_pdf(fields: LetterFields, *, compress: bool = True) -> bytes:
    """Lay the letter out on an A4 page. compress=False keeps the text readable
    in the raw PDF bytes, which tests use to check what was printed."""
    text = Template(TEMPLATE.read_text(encoding="utf-8")).substitute(asdict(fields))

    pdf = FPDF(format="A4")
    pdf.set_compression(compress)
    pdf.set_title(f"ETLS facility letter {fields.file_reference}")
    pdf.set_margins(left=25, top=25, right=25)
    pdf.add_page()
    for line in text.splitlines():
        bold = line.startswith("**") and line.endswith("**") and len(line) > 4
        pdf.set_font("Helvetica", style="B" if bold else "", size=11)
        content = line[2:-2] if bold else line
        # multi_cell wraps long lines inside the margins; an empty line is a gap.
        pdf.multi_cell(w=0, h=6, text=_latin1(content) or " ", new_x="LMARGIN", new_y="NEXT")
    return bytes(pdf.output())
