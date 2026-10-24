"""ETLS facility letters: the form (a draft until submitted), the duplicate check, and the HS code."""

from datetime import date

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit.service import record_event
from app.core.dates import add_months, long_date
from app.core.documents import facts
from app.core.identity.models import User
from app.core.workflow import checks, effects, flags, summaries
from app.core.workflow import service as workflow
from app.core.workflow.delegation import today
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
CHECK_DUPLICATES = "etls_check_duplicate_certificates"  # transition effect, on "Submit"
CERTIFICATES_VALID = "etls_certificates_valid"  # check on "Verify": none past six months
CERTIFICATES_EXPIRING = "etls_certificates_expiring"  # warning on "Submit": one expires soon
VALID_MONTHS = 6
WARN_DAYS = 30


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
        .join(Case, Case.id == FacilityLetterCertificate.case_id)
        .where(
            FacilityLetterCertificate.number_normalized.in_(numbers),
            FacilityLetterCertificate.case_id != case_id,
            # Only submitted cases: a draft's numbers aren't "used" yet.
            Case.reference.is_not(None),
        )
        .order_by(FacilityLetterCertificate.case_id)
    )
    uses: dict[str, list[int]] = {}
    for number, earlier_case_id in rows:
        uses.setdefault(number, []).append(earlier_case_id)
    return uses


def _form_rows(form: FacilityLetterForm) -> dict:
    """The form's own columns, as stored."""
    return {
        "importer_name": form.importer_name,
        "importer_address": form.importer_address,
        "product": form.product,
        "hs_code": form.hs_code,
        "quantity": form.quantity,
        "unit": form.unit,
        "exporter_name": form.exporter_name,
        "exporter_country": form.exporter_country,
        "exporter_etls_approval_number": form.exporter_etls_approval_number,
    }


def _children(case_id: int, form: FacilityLetterForm) -> list:
    """One row per product approval and per certificate of origin."""
    return [
        *(FacilityLetterProductApproval(case_id=case_id, number=n) for n in form.product_approval_numbers),
        *(
            FacilityLetterCertificate(
                case_id=case_id,
                number=c.number,
                number_normalized=normalize_certificate_number(c.number),
                issued_on=c.issued_on,
            )
            for c in form.certificates_of_origin
        ),
    ]


def _snapshot(fields: dict, approvals: list[str], certificates: list) -> dict:
    """The form as plain JSON values, for comparing before and after an edit."""
    return {
        **{k: format(v.normalize(), "f") if k == "quantity" else v for k, v in fields.items()},
        "product_approval_numbers": approvals,
        "certificates_of_origin": [
            {"number": c.number, "issued_on": c.issued_on.isoformat() if c.issued_on else None}
            for c in certificates
        ],
    }


async def create_draft(session: AsyncSession, *, actor: User, form: FacilityLetterForm) -> FacilityLetter:
    """Open an etls_facility_letter case as a draft, with the importer's form,
    in one transaction. It gets its reference when the applicant submits."""
    case = await workflow.open_case(
        session, workflow_code=FACILITY_LETTER, actor=actor, module=MODULE
    )
    session.add(FacilityLetter(case_id=case.id, **_form_rows(form)))
    await session.flush()  # the parent row first: the child rows point at it
    session.add_all(_children(case.id, form))
    # The case, its audit row and the form are saved together, or not at all.
    await session.commit()
    return await _reloaded(session, case.id)


async def _reloaded(session: AsyncSession, case_id: int) -> FacilityLetter:
    # Read back what was stored (e.g. quantity 1200.5 comes back as 1200.500),
    # child rows included, so the response matches every later GET.
    letter = await session.get(FacilityLetter, case_id)
    await session.refresh(letter)
    return letter


async def update_form(
    session: AsyncSession, *, case_id: int, actor: User, form: FacilityLetterForm
) -> FacilityLetter:
    """Replace the form of a case the applicant may still change (a draft).

    The whole form is sent each time, as the screen has it. The audit row
    lists each field that changed, before and after, so staff can see exactly
    what an applicant corrected.
    """
    letter = await get_facility_letter(session, case_id, actor)
    case = await workflow.get_case(session, case_id, actor, for_update=True)
    if not workflow.acts_as_applicant(case, actor):
        raise workflow.NotPermitted("Only the applicant can change the application form.")
    if not case.current_status.applicant_editable:
        raise workflow.TransitionNotAllowed("The form can't be changed once the application is submitted.")

    before = _snapshot(
        {k: getattr(letter, k) for k in _form_rows(form)},
        [a.number for a in letter.product_approvals],
        list(letter.certificates),
    )
    after = _snapshot(_form_rows(form), list(form.product_approval_numbers), list(form.certificates_of_origin))
    changes = {k: {"from": before[k], "to": after[k]} for k in after if before[k] != after[k]}
    if not changes:
        return letter

    for column, value in _form_rows(form).items():
        setattr(letter, column, value)
    details = {"changes": changes}
    if letter.hs_code_confirmed and ({"product", "hs_code"} & changes.keys()):
        # The desk confirmed a code for the goods as they were. New goods (after
        # a return) need it confirmed again, or the receipt rule and the letter
        # would use a code nobody checked against them.
        details["hs_code_confirmation_cleared"] = letter.hs_code_confirmed
        letter.hs_code_confirmed = letter.hs_code_confirmed_by = letter.hs_code_confirmed_at = None
    # Child rows are replaced, not edited: delete them all, then add the new list.
    for table in (FacilityLetterProductApproval, FacilityLetterCertificate):
        await session.execute(delete(table).where(table.case_id == case.id))
    session.add_all(_children(case.id, form))
    case.updated_at = func.now()  # not status_changed_at: editing doesn't move the case
    record_event(
        session,
        actor=actor,
        action="case.form_updated",
        entity_type=workflow.AUDIT_ENTITY,
        entity_id=case.id,
        details=details,
    )
    await session.commit()
    return await _reloaded(session, case.id)


async def check_duplicates(session: AsyncSession, move: effects.Move) -> None:
    """The effect of submitting: hold the case for the desk if a certificate of
    origin number was already used on an earlier submitted case.

    A repeat isn't refused (the importer might have a good reason, e.g. a split
    shipment), but the case is held for the ETLS desk to look at. On a
    resubmission, only numbers that no open flag covers yet raise a new one.
    [CONFIRM] Should a number from a rejected case also count as used?
    (Right now every earlier submitted use counts.)
    """
    case = move.case
    letter = await session.get(FacilityLetter, case.id)
    earlier = await _earlier_uses(session, case.id, [c.number_normalized for c in letter.certificates])
    flagged = {
        number
        for f in await flags.open_flags(session, case.id)
        if f.code == DUPLICATE_CERTIFICATE
        for number in f.details.get("numbers", [])
    }
    earlier = {n: ids for n, ids in earlier.items() if n not in flagged}
    if earlier:
        await flags.raise_flag(
            session,
            case_id=case.id,
            code=DUPLICATE_CERTIFICATE,
            message="Certificate of origin number(s) already used on an earlier case: "
            + ", ".join(sorted(earlier)),
            for_position_code=DESK,
            details={"numbers": sorted(earlier), "earlier_case_ids": earlier},
        )


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


def certificate_expiry(certificate: FacilityLetterCertificate) -> date | None:
    """The last day the certificate is valid: six months after its issue date."""
    return add_months(certificate.issued_on, VALID_MONTHS) if certificate.issued_on else None


async def _check_certificates_valid(session: AsyncSession, case: Case) -> list[str]:
    """Blocks Verify: a certificate more than six months past its issue date, or with no date."""
    letter = await session.get(FacilityLetter, case.id)
    problems = []
    for certificate in letter.certificates if letter else []:
        expiry = certificate_expiry(certificate)
        if expiry is None:
            problems.append(f"the issue date of certificate of origin {certificate.number} isn't recorded")
        elif today() > expiry:
            problems.append(
                f"certificate of origin {certificate.number} expired on {long_date(expiry)} "
                f"(issued {long_date(certificate.issued_on)})"
            )
    return problems


async def _check_certificates_expiring(session: AsyncSession, case: Case) -> list[str]:
    """A warning on Submit: a certificate that has expired or will within 30 days.
    The applicant may still submit; the desk can't verify once it's expired."""
    letter = await session.get(FacilityLetter, case.id)
    found = []
    for certificate in letter.certificates if letter else []:
        expiry = certificate_expiry(certificate)
        if expiry is None or (expiry - today()).days > WARN_DAYS:
            continue
        verb = "expired" if expiry < today() else "expires"
        found.append(
            f"certificate of origin {certificate.number} {verb} on {long_date(expiry)}; "
            "the Ministry can't verify your application with an expired certificate"
        )
    return found


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
    return {
        "product": letter.product,
        "unit": letter.unit,
        "exporter_country": letter.exporter_country,
        # None until someone gives an HS code: a rule on it is then "not known
        # yet" (see core documents/conditions.py), decided once the desk enters it.
        "hs_heading": hs_heading(letter),
    }


async def facility_letter_summaries(session: AsyncSession, case_ids: list[int]) -> dict[int, str]:
    """The goods, for lists and queues: "Roofing sheets, 1200.5 tonnes"."""
    letters = await session.scalars(select(FacilityLetter).where(FacilityLetter.case_id.in_(case_ids)))
    # normalize() drops NUMERIC's trailing zeros (1200.500 -> 1200.5).
    return {l.case_id: f"{l.product}, {format(l.quantity.normalize(), 'f')} {l.unit}" for l in letters}


# Registered when the module is imported (main.py imports its router).
facts.register(FACILITY_LETTER, facility_letter_facts)
summaries.register(FACILITY_LETTER, facility_letter_summaries)
checks.register(HS_CODE_CONFIRMED, _check_hs_code_confirmed)
checks.register(CERTIFICATES_VALID, _check_certificates_valid)
checks.register(CERTIFICATES_EXPIRING, _check_certificates_expiring)
effects.register(CHECK_DUPLICATES, check_duplicates)
