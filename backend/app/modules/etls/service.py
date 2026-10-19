"""ETLS facility letters: opening a case together with its form."""

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.identity.models import User
from app.core.workflow import service as workflow
from app.modules.etls.models import (
    FacilityLetter,
    FacilityLetterCertificate,
    FacilityLetterProductApproval,
)
from app.modules.etls.schemas import FacilityLetterForm, normalize_certificate_number

MODULE = "etls"
FACILITY_LETTER = "etls_facility_letter"


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
    # The case, its audit row and the form are saved together, or not at all.
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
