"""ETLS facility letters: the form (a draft until submitted), the duplicate check, and the HS code."""

from datetime import date

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit.service import record_event
from app.core.dates import add_months, long_date
from app.core.documents import facts
from app.core.documents import service as documents
from app.core.identity import password_links
from app.core.identity import service as identity
from app.core.identity.models import User
from app.core.workflow import checklist, checks, effects, flags, summaries
from app.core.workflow import service as workflow
from app.core.workflow.delegation import today
from app.core.workflow.models import Case, WorkflowStatus
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
FORM_COMPLETE = "etls_form_complete"  # check on "Submit" and "Resubmit": nothing left empty
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
        **{k: format(v.normalize(), "f") if k == "quantity" and v is not None else v for k, v in fields.items()},
        "product_approval_numbers": approvals,
        "certificates_of_origin": [
            {"number": c.number, "issued_on": c.issued_on.isoformat() if c.issued_on else None}
            for c in certificates
        ],
    }


async def create_draft(
    session: AsyncSession, *, actor: User, form: FacilityLetterForm, applicant: User | None = None
) -> FacilityLetter:
    """Open an etls_facility_letter case as a draft, with the importer's form,
    in one transaction. It gets its reference when the applicant submits.
    `applicant` is set when Records opens it for a walk-in."""
    case = await workflow.open_case(
        session, workflow_code=FACILITY_LETTER, actor=actor, module=MODULE, applicant=applicant
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


async def open_walk_in(
    session: AsyncSession, *, actor: User, email: str | None, full_name: str, form: FacilityLetterForm
) -> FacilityLetter:
    """Records opens a draft for an applicant who came in person.

    The case belongs to the applicant's account, found by email, or made now
    if they have none. A new account has no password: nobody can log in to
    it until the applicant sets one with the link emailed now (with the
    case, in one transaction). An account that still has no password gets a
    fresh link on each walk-in, which ends the older one.

    With no email, a new account is made each time, which can't log in or be
    emailed: Records finishes the application and tells them of each step.
    """
    if not await workflow.may_open_walk_in(session, FACILITY_LETTER, actor):
        # Checked before an account might be made.
        raise workflow.NotPermitted("Your post can't open applications for walk-in applicants.")
    applicant = await identity.get_user_by_email(session, email) if email else None
    if applicant is None:
        applicant = await identity.create_user(
            session,
            email=email,
            full_name=full_name,
            password=None,
            role_codes=["applicant"],
        )
        record_event(
            session,
            actor=actor,
            action="user.created_for_walk_in",
            entity_type=identity.AUDIT_ENTITY,
            entity_id=applicant.id,
            details={"email": applicant.email},
        )
    elif not applicant.is_active or applicant.role_codes != {"applicant"}:
        # Never attach an application to a staff member's or a closed account.
        raise workflow.NotPermitted("That email belongs to an account that can't apply.")
    if applicant.email is not None and applicant.password_hash is None:
        await password_links.issue_link(session, user=applicant, actor=actor)
    return await create_draft(session, actor=actor, form=form, applicant=applicant)


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


# What Submit needs filled in, in the form's order, as the applicant sees it.
# The HS code isn't here: the applicant may leave it to the desk (step 6k).
REQUIRED_FIELDS = {
    "importer_name": "Importer's business name",
    "importer_address": "Importer's address",
    "product": "Product",
    "quantity": "Quantity",
    "unit": "Unit",
    "exporter_name": "Exporter's name",
    "exporter_country": "Exporter's country",
    "exporter_etls_approval_number": "Exporter's ETLS approval number",
}


def form_gaps(letter: FacilityLetter) -> list[str]:
    """What's still empty on the form, e.g. ["Quantity is missing", ...]."""
    gaps = [f"{label} is missing" for column, label in REQUIRED_FIELDS.items() if getattr(letter, column) is None]
    if not letter.product_approvals:
        gaps.append("Product approval number is missing")
    if not letter.certificates:
        gaps.append("Certificate of origin number is missing")
    gaps += [
        f"Issue date of certificate of origin {c.number} is missing" for c in letter.certificates if c.issued_on is None
    ]
    return gaps


async def _check_form_complete(session: AsyncSession, case: Case) -> list[str]:
    """Blocks Submit and Resubmit until every required field is filled in, so
    every step after Submit (Records, the desk, the letter) has a whole form."""
    letter = await session.get(FacilityLetter, case.id)
    return form_gaps(letter) if letter else ["The application form is missing"]


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


async def other_uses(session: AsyncSession, case_id: int, user: User) -> dict[str, list]:
    """For the desk (S2): each of this case's certificate numbers that another
    submitted case also used (earlier or later), with that case's reference,
    status and date.

    Read live, so the desk sees where the earlier case is *now* (e.g. since
    rejected), not where it was when the flag was raised."""
    letter = await get_facility_letter(session, case_id, user)
    if not workflow.is_staff(user):
        raise workflow.NotPermitted("Only Ministry staff can see other applicants' cases.")
    other = FacilityLetterCertificate.__table__.alias("other")
    rows = await session.execute(
        select(FacilityLetterCertificate.number, Case, WorkflowStatus, FacilityLetter.importer_name)
        .join(other, other.c.number_normalized == FacilityLetterCertificate.number_normalized)
        .join(Case, Case.id == other.c.case_id)
        .join(WorkflowStatus, WorkflowStatus.id == Case.current_status_id)
        .join(FacilityLetter, FacilityLetter.case_id == Case.id)
        .where(
            FacilityLetterCertificate.case_id == letter.case_id,
            Case.id != letter.case_id,
            Case.reference.is_not(None),  # drafts don't count, as in the check
        )
        .order_by(FacilityLetterCertificate.number, Case.submitted_at, Case.id)
    )
    found: dict[str, list] = {}
    for number, case, status, importer in rows:
        found.setdefault(number, []).append((case, status, importer))
    return found


async def checks_summary(session: AsyncSession, case_id: int, user: User) -> dict:
    """Every check made on the application so far, for the PS before signing
    (SCREENS.md S3) and the desk: originals seen, the ECOWAS list ticks, the
    duplicate flags, the confirmed HS code, certificate validity and
    documents. Read from the same records the moves check."""
    letter = await get_facility_letter(session, case_id, user)
    if not workflow.is_staff(user):
        raise workflow.NotPermitted("Only Ministry staff can see the checks.")
    case = await workflow.get_case(session, case_id, user)
    requirements = await documents.checklist(session, case)
    ticks = await checklist.checklist(session, case)
    case_flags = [f for f in await flags.case_flags(session, case.id) if f.code == DUPLICATE_CERTIFICATE]

    user_ids = {letter.hs_code_confirmed_by, *(t.ticked_by for t in ticks)}
    user_ids |= {s.documents[0].original_seen_by for s in requirements if s.requirement.original_required and s.documents}
    names = {
        u.id: u.full_name for u in await session.scalars(select(User).where(User.id.in_({i for i in user_ids if i})))
    }
    return {
        "originals": [
            {
                "document": s.requirement.document_type.name,
                "seen": not s.original_pending,
                "seen_at": s.documents[0].original_seen_at if s.documents else None,
                "seen_by": names.get(s.documents[0].original_seen_by) if s.documents else None,
            }
            for s in requirements
            if s.applies is True and s.requirement.original_required
        ],
        "checklist": [
            {"label": t.item.label, "ticked": t.ticked, "ticked_at": t.ticked_at, "ticked_by": names.get(t.ticked_by)}
            for t in ticks
        ],
        "duplicate_flags": [
            {"message": f.message, "resolved": f.resolved_at is not None, "resolution": f.resolution}
            for f in case_flags
        ],
        "hs_code_confirmed": letter.hs_code_confirmed,
        "hs_code_confirmed_by": names.get(letter.hs_code_confirmed_by),
        "certificates": [
            {
                "number": c.number,
                "issued_on": c.issued_on,
                "expires_on": certificate_expiry(c),
                "valid_today": certificate_expiry(c) is not None and today() <= certificate_expiry(c),
            }
            for c in letter.certificates
        ],
        "documents_missing": [s.requirement.document_type.name for s in requirements if s.missing],
    }


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
    """The 4-digit HS heading (2523 = cement), from the code the desk confirmed.

    The applicant's declared code never decides it (SCREENS.md A2): until the
    desk confirms, whether the cement receipt is needed is "not known yet"."""
    code = letter.hs_code_confirmed
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
    return {l.case_id: _goods(l) for l in letters}


def _goods(letter: FacilityLetter) -> str:
    # normalize() drops NUMERIC's trailing zeros (1200.500 -> 1200.5). A draft
    # may have no product or quantity yet: show what there is.
    amount = " ".join(
        p for p in (format(letter.quantity.normalize(), "f") if letter.quantity else None, letter.unit) if p
    )
    return ", ".join(p for p in (letter.product, amount) if p) or "Not filled in yet"


# Registered when the module is imported (main.py imports its router).
facts.register(FACILITY_LETTER, facility_letter_facts)
summaries.register(FACILITY_LETTER, facility_letter_summaries)
checks.register(HS_CODE_CONFIRMED, _check_hs_code_confirmed)
checks.register(CERTIFICATES_VALID, _check_certificates_valid)
checks.register(CERTIFICATES_EXPIRING, _check_certificates_expiring)
checks.register(FORM_COMPLETE, _check_form_complete)
effects.register(CHECK_DUPLICATES, check_duplicates)
