"""Two authorised signatories press "Sign" on the same letter at the same moment.

The step is in both their queues while the Director is away; whoever acts
first claims it. change_status() locks the case row (SELECT ... FOR UPDATE),
so the second waits, then finds the case already signed and is refused. One
signing, one letter.

Like test_case_race.py this needs real commits on separate connections, so it
can't use the rolled-back db_session. Each request gets its own session, as
in the running API. Its rows stay until the next run rebuilds the database,
so it uses its own "race-sig-" emails and certificate number, and on the way
out takes back the posts, ends the absence and empties the list.
"""

import asyncio
import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit.models import AuditEvent
from app.core.documents.models import IssuedDocument
from app.core.identity.service import assign_position, create_user
from app.core.workflow import service
from app.db.session import get_session
from app.main import app
from tests.support import TEST_PASSWORD, add_signatory, record_absence, verified_case

pytestmark = pytest.mark.anyio


@pytest.fixture
async def committing_act(committing_engine, auth_headers):
    """Like `act`, but every request runs in its own session that really commits."""

    async def own_session():
        async with AsyncSession(committing_engine, expire_on_commit=False) as session:
            yield session

    app.dependency_overrides[get_session] = own_session
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:

        async def _act(user, method, url, headers_extra=None, **kwargs):
            headers = {**auth_headers(user), **(headers_extra or {})}
            return await getattr(client, method)(url, headers=headers, **kwargs)

        yield _act
    app.dependency_overrides.clear()


@pytest.fixture
async def race_people(committing_engine):
    run = uuid.uuid4().hex[:8]
    async with AsyncSession(committing_engine, expire_on_commit=False) as session:

        async def user(key, roles, position=None):
            person = await create_user(
                session,
                email=f"race-sig-{key}-{run}@test.gm",
                full_name=f"Race {key}",
                password=TEST_PASSWORD,
                role_codes=roles,
            )
            if position:
                await assign_position(session, user=person, position_code=position, actor=None)
            return person

        people = {
            "applicant": await user("applicant", ["applicant"]),
            "records_officer": await user("records", ["records_officer"], "records_officer"),
            "desk": await user("desk", ["officer"], "etls_desk_officer"),
            "director": await user("director", ["director"], "director_of_industry"),
            "admin": await user("admin", ["officer", "signatory_admin"]),
            "first": await user("first", ["officer"]),
            "second": await user("second", ["officer"]),
        }
    yield people

    async with AsyncSession(committing_engine) as session:
        ids = {"ids": [p.id for p in people.values()]}
        # Without this a "race" Director would still hold the post, and be away,
        # in every later test, and the two race signatories would stay on the list.
        await session.execute(text("DELETE FROM core.position_holders WHERE user_id = ANY(:ids)"), ids)
        await session.execute(
            text(
                "UPDATE core.absences SET cancelled_at = now(), cancelled_by = user_id "
                "WHERE user_id = ANY(:ids) AND cancelled_at IS NULL"
            ),
            ids,
        )
        await session.execute(
            text(
                "UPDATE core.authorised_signatories SET removed_at = now(), removed_by = added_by "
                "WHERE user_id = ANY(:ids) AND removed_at IS NULL"
            ),
            ids,
        )
        await session.commit()


async def test_two_signatories_signing_at_once_sign_once(committing_act, committing_engine, race_people, monkeypatch):
    act, people = committing_act, race_people
    # This case is committed: number it in a year no other test uses, or it
    # would take this year's FL/0001 from the tests that expect it (demo seed).
    real_today = service.today()
    monkeypatch.setattr(service, "today", lambda: real_today.replace(year=2095))
    case_id = await verified_case(act, people, certificate_of_origin_numbers=[f"RACE-CO-{uuid.uuid4().hex[:10]}"])
    for person in (people["first"], people["second"]):
        assert (await add_signatory(act, people["admin"], person)).status_code == 201
    assert (await record_absence(act, people["director"])).status_code == 201

    async def sign(person):
        return await act(person, "post", f"/cases/{case_id}/status", json={"to_status": "signed"})

    responses = await asyncio.gather(sign(people["first"]), sign(people["second"]))

    assert sorted(r.status_code for r in responses) == [200, 409], [r.text for r in responses]
    async with AsyncSession(committing_engine) as check:
        signings = (
            await check.scalars(
                select(AuditEvent).where(
                    AuditEvent.entity_type == "case",
                    AuditEvent.entity_id == str(case_id),
                    AuditEvent.action == "case.status_changed",
                    AuditEvent.details["to"].astext == "signed",
                )
            )
        ).all()
        letters = await check.scalar(
            select(func.count()).select_from(IssuedDocument).where(IssuedDocument.case_id == case_id)
        )
    assert len(signings) == 1
    assert letters == 1
    winner = next(p for p, r in zip((people["first"], people["second"]), responses) if r.status_code == 200)
    assert signings[0].actor_user_id == winner.id
    assert signings[0].details["basis"] == "signatory"
