"""ETLS facility letters: opening a case together with its form, and the HS code."""

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit.service import record_event
from app.core.documents import facts
from app.core.identity.models import User
from app.core.workflow import checks, flags
from app.core.workflow import service as workflow
from app.core.workflow.models import Case
from app.modules.etls.models import (
    FacilityLetter,
    FacilityLetterCertificate,
    FacilityLetterProductApproval,
)
from app.modules.etls.schemas import FacilityLetterForm, normalize_certificate_number

MODULE = "etls"
FACILITY_LETTER = "etls_facility_letter"
DUPLICATE_CERTIFICATE = "etls.duplicate_certificate_of_origin"
DESK = "etls_desk_officer"
HS_CODE_CONFIRMED = "hs_code_confirmed"  # transition check, on the desk's "Verify" move


async def _earlier_uses(session: AsyncSession, case_id: int, numbers: list[str]) -> dict[str, list[int]]:
    """{normalized number: ids of other cases that already used it}.

    First takes a transaction-level advisory lock per number, in sorted order.
    Two submissions with the same number then run this check one after the
    other: the second waits until the first commits, and so sees its rows.
    Without the lock both could check at the same moment, find nothing, and
    both go through. Sorting stops two submissions deadlocking on each other.
    The locks are released automatically at commit or rollback.
    """
    for number in sorted(numbers):
        await session.execute(
            select(func.pg_advisory_xact_lock(func.hashtextextended(f"etls.coo:{number}", 0)))
        )
    rows = await session.execute(
        select(FacilityLetterCertificate.number_normalized, FacilityLetterCertificate.case_id)
        .where(
            FacilityLetterCertificate.number_normalized.in_(numbers),
            FacilityLetterCertificate.case_id != case_id,
        )
        .order_by(FacilityLetterCertificate.case_id)
    )
    uses: dict[str, list[int]] = {}
    for number, earlier_case_id in rows:
        uses.setdefault(number, []).append(earlier_case_id)
    return uses


async def submit_facility_letter(
    session: AsyncSession, *, actor: User, form: FacilityLetterForm
) -> FacilityLetter:
    """Open an etls_facility_letter case with the importer's form, in one transaction."""
    case = await workflow.open_case(
        session, workflow_code=FACILITY_LETTER, actor=actor, module=MODULE
    )
    letter = FacilityLetter(
        case_id=case.id,
        importer_name=form.importer_name,
        importer_address=form.importer_address,
        product=form.product,
        hs_code=form.hs_code,
        quantity=form.quantity,
        unit=form.unit,
        exporter_name=form.exporter_name,
        exporter_country=form.exporter_country,
        exporter_etls_approval_number=form.exporter_etls_approval_number,
        product_approvals=[
            FacilityLetterProductApproval(number=n) for n in form.product_approval_numbers
        ],
        certificates=[
            FacilityLetterCertificate(number=n, number_normalized=normalize_certificate_number(n))
            for n in form.certificate_of_origin_numbers
        ],
    )
    session.add(letter)
    await session.flush()

    # Certificate of origin numbers must be unique across all cases. A repeat
    # isn't refused (the importer might have a good reason, e.g. a split
    # shipment), but the case is held for the ETLS desk to look at.
    # [CONFIRM] Should a number from a rejected case also count as used?
    # (Right now every earlier use counts.)
    normalized = [c.number_normalized for c in letter.certificates]
    if earlier := await _earlier_uses(session, case.id, normalized):
        await flags.raise_flag(
            session,
            case_id=case.id,
            code=DUPLICATE_CERTIFICATE,
            message="Certificate of origin number(s) already used on an earlier case: "
            + ", ".join(sorted(earlier)),
            for_position_code=DESK,
            details={"numbers": sorted(earlier), "earlier_case_ids": earlier},
        )

    # The case, its audit row, the form and any flag are saved together, or not at all.
    await session.commit()
    # Re-read what was stored (e.g. quantity 1200.5 comes back as 1200.500), so
    # this response matches every later GET.
    await session.refresh(letter)
    return letter


async def get_facility_letter(session: AsyncSession, case_id: int, user: User) -> FacilityLetter:
    # The core decides who may see the case (and gives the same 404 otherwise).
    case = await workflow.get_case(session, case_id, user)
    letter = None
    if case.workflow.code == FACILITY_LETTER:
        letter = await session.get(FacilityLetter, case.id)
    if letter is None:
        raise workflow.NotFound("Facility letter not found.")
    return letter


async def confirm_hs_code(session: AsyncSession, case_id: int, actor: User, hs_code: str) -> FacilityLetter:
    """An officer confirms the HS code, or corrects the applicant's.

    Allowed for whoever may make the move that needs it (the desk's "Verify",
    or someone acting for the desk), so no post is named here. It can be
    changed again until the case is verified; each change is audited.
    """
    letter = await get_facility_letter(session, case_id, actor)
    case = await workflow.get_case(session, case_id, actor, for_update=True)
    if not await workflow.may_make_move_with_check(session, case, actor, HS_CODE_CONFIRMED):
        raise workflow.NotPermitted("Only the officer verifying this file can confirm its HS code.")

    previous = letter.hs_code_confirmed
    letter.hs_code_confirmed = hs_code
    letter.hs_code_confirmed_by = actor.id
    letter.hs_code_confirmed_at = func.now()
    record_event(
        session,
        actor=actor,
        action="case.hs_code_confirmed",
        entity_type=workflow.AUDIT_ENTITY,
        entity_id=case.id,
        details={"declared": letter.hs_code, "confirmed": hs_code, "previously_confirmed": previous},
    )
    await session.commit()
    await session.refresh(letter)
    return letter


async def _check_hs_code_confirmed(session: AsyncSession, case: Case) -> list[str]:
    letter = await session.get(FacilityLetter, case.id)
    if letter is None or letter.hs_code_confirmed is None:
        return ["the HS code hasn't been confirmed by an officer"]
    return []


def hs_heading(letter: FacilityLetter) -> str | None:
    """The 4-digit HS heading (2523 = cement): the officer's code once confirmed,
    the applicant's until then."""
    code = letter.hs_code_confirmed or letter.hs_code
    return code[:4] if code else None


async def facility_letter_facts(session: AsyncSession, case_id: int) -> dict:
    """What document conditions may test on a facility letter case (see core documents/facts.py)."""
    letter = await session.get(FacilityLetter, case_id)
    if letter is None:
        return {}
    found = {
        "product": letter.product,
        "unit": letter.unit,
        "exporter_country": letter.exporter_country,
    }
    # Left out when unknown (a case from before 0020), so a rule on it fails
    # closed: the document counts as required.
    if heading := hs_heading(letter):
        found["hs_heading"] = heading
    return found


# Registered when the module is imported (main.py imports its router).
facts.register(FACILITY_LETTER, facility_letter_facts)
checks.register(HS_CODE_CONFIRMED, _check_hs_code_confirmed)
