from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.identity.deps import get_current_user
from app.core.identity.models import User
from app.core.workflow import service as workflow
from app.db.session import get_session
from app.modules.etls import service
from app.modules.etls.models import FacilityLetter
from app.modules.etls.schemas import FacilityLetterForm, FacilityLetterOut

# Engine errors (WorkflowError) are turned into HTTP statuses by the handler in main.py.
router = APIRouter(prefix="/etls", tags=["etls"])


async def _out(session: AsyncSession, letter: FacilityLetter, user: User) -> FacilityLetterOut:
    case = await workflow.get_case(session, letter.case_id, user)
    return FacilityLetterOut(
        case_id=letter.case_id,
        status=case.current_status.code,
        importer_name=letter.importer_name,
        importer_address=letter.importer_address,
        product=letter.product,
        quantity=letter.quantity,
        unit=letter.unit,
        exporter_name=letter.exporter_name,
        exporter_country=letter.exporter_country,
        exporter_etls_approval_number=letter.exporter_etls_approval_number,
        product_approval_numbers=[a.number for a in letter.product_approvals],
        certificate_of_origin_numbers=[c.number for c in letter.certificates],
    )


@router.post("/facility-letters", response_model=FacilityLetterOut, status_code=status.HTTP_201_CREATED)
async def submit_facility_letter(
    body: FacilityLetterForm,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    letter = await service.submit_facility_letter(session, actor=user, form=body)
    return await _out(session, letter, user)


@router.get("/facility-letters/{case_id}", response_model=FacilityLetterOut)
async def get_facility_letter(
    case_id: int,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    return await _out(session, await service.get_facility_letter(session, case_id, user), user)
