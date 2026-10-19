"""Two officers act on the same case at the same moment: only one may win.

This needs two real database connections committing for real, so it can't use
the rolled-back db_session. Its rows stay until the next test run rebuilds the
database, which is why it uses its own "race-" emails.
"""

import asyncio

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit.models import AuditEvent
from app.core.identity.models import User
from app.core.identity.service import assign_position, create_user
from app.core.workflow import service
from tests.support import TEST_PASSWORD

pytestmark = pytest.mark.anyio


async def _user(session, role, position=None, email=None):
    user = await create_user(
        session,
        email=email or f"race-{role}@test.gm",
        full_name=role,
        password=TEST_PASSWORD,
        role_codes=[role],
    )
    if position:
        await assign_position(session, user=user, position_code=position, actor=None)
    return user


@pytest.fixture
async def release_posts(committing_engine):
    """Take the race users' posts away again when the test ends, pass or fail.

    Their rows are committed, so without this a "race" Minister would still hold
    the Minister's post in later tests, and count as present when those tests
    mark their own Minister absent.
    """
    yield
    async with AsyncSession(committing_engine) as session:
        await session.execute(
            text(
                "DELETE FROM core.position_holders WHERE user_id IN "
                "(SELECT id FROM core.users WHERE email LIKE 'race-%')"
            )
        )
        await session.commit()


async def test_simultaneous_approve_and_reject_cannot_both_succeed(committing_engine, release_posts):
    async with AsyncSession(committing_engine, expire_on_commit=False) as setup:
        applicant = await _user(setup, "applicant")
        people = {
            role: await _user(setup, role, position)
            for role, position in [
                ("records_officer", "records_officer"),
                ("minister", "minister"),
                ("permanent_secretary", "permanent_secretary"),
                ("director", "director_of_industry"),
            ]
        }
        officer_a = await _user(setup, "officer", "industry_officer", email="race-officer-a@test.gm")
        officer_b = await _user(setup, "officer", "industry_officer", email="race-officer-b@test.gm")
        case = await service.start_case(setup, workflow_code="etls_application", actor=applicant)
        for role, to_status in [
            ("records_officer", "with_minister"),
            ("minister", "with_ps"),
            ("permanent_secretary", "with_director"),
            ("director", "with_officer"),
        ]:
            await service.change_status(
                setup, case_id=case.id, to_status_code=to_status, actor=people[role]
            )

    async def attempt(officer_id: int, to_status: str) -> str:
        # Each attempt has its own session, so its own connection and transaction,
        # just like two separate HTTP requests.
        async with AsyncSession(committing_engine, expire_on_commit=False) as session:
            officer = await session.get(User, officer_id)
            try:
                await service.change_status(
                    session, case_id=case.id, to_status_code=to_status, actor=officer
                )
                return "moved"
            except service.TransitionNotAllowed:
                return "refused"

    results = await asyncio.gather(
        attempt(officer_a.id, "approved"), attempt(officer_b.id, "rejected")
    )

    # The second one waited for the first one's lock, then found the case
    # already final, so it had no moves left.
    assert sorted(results) == ["moved", "refused"]

    async with AsyncSession(committing_engine) as check:
        final_moves = (
            await check.scalars(
                select(AuditEvent).where(
                    AuditEvent.entity_type == "case",
                    AuditEvent.entity_id == str(case.id),
                    AuditEvent.details["from"].astext == "with_officer",
                )
            )
        ).all()
    assert len(final_moves) == 1
