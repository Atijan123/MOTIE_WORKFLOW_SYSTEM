"""Checks on workflow *data*. Because workflows live in tables, a bad migration
could create a workflow that traps cases or can never finish. These tests
check the shape of every workflow in the database, not just ETLS."""

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError

from app.core.workflow.models import Workflow, WorkflowStatus, WorkflowTransition

pytestmark = pytest.mark.anyio


async def _definition(session, workflow):
    statuses = (
        await session.scalars(select(WorkflowStatus).where(WorkflowStatus.workflow_id == workflow.id))
    ).all()
    transitions = (
        await session.scalars(
            select(WorkflowTransition).where(WorkflowTransition.workflow_id == workflow.id)
        )
    ).all()
    return statuses, transitions


async def test_etls_workflow_is_seeded(db_session):
    workflow = await db_session.scalar(select(Workflow).where(Workflow.code == "etls_application"))
    assert workflow is not None
    assert workflow.start_role.code == "applicant"

    statuses, transitions = await _definition(db_session, workflow)
    # 6 seeded in 0005, plus "With the PS" from 0012.
    assert len(statuses) == 7
    # Guards against a misspelt code in a migration: that row would be skipped silently.
    # 7 seeded in 0005, minus the PS placeholder (0011), plus the PS's own step (0012).
    assert len(transitions) == 7


async def test_etls_route_is_the_one_the_ministry_confirmed(db_session):
    # Records -> Minister -> PS -> Director of Industry and Investment, who signs
    # and assigns to an officer (confirmed 2026-10-19). The officer's three moves
    # are still placeholders [CONFIRM].
    rows = (
        await db_session.execute(
            text(
                "SELECT f.code, t.code, p.code, x.name FROM core.workflow_transitions x "
                "JOIN core.workflows w ON w.id = x.workflow_id "
                "JOIN core.workflow_statuses f ON f.id = x.from_status_id "
                "JOIN core.workflow_statuses t ON t.id = x.to_status_id "
                "JOIN core.positions p ON p.id = x.required_position_id "
                "WHERE w.code = 'etls_application'"
            )
        )
    ).all()
    assert {tuple(r) for r in rows} == {
        ("submitted", "with_minister", "records_officer", "Register and forward to the Minister"),
        ("with_minister", "with_ps", "minister", "Minute to the Permanent Secretary"),
        ("with_ps", "with_director", "permanent_secretary", "Minute to the Director"),
        ("with_director", "with_officer", "director_of_industry", "Sign and assign to an officer"),
        ("with_officer", "with_director", "industry_officer", "Return to the Director"),
        ("with_officer", "approved", "industry_officer", "Approve"),
        ("with_officer", "rejected", "industry_officer", "Reject"),
    }


async def test_every_workflow_is_well_formed(db_session):
    for workflow in (await db_session.scalars(select(Workflow))).all():
        statuses, transitions = await _definition(db_session, workflow)
        outgoing = {s.id: [t for t in transitions if t.from_status_id == s.id] for s in statuses}

        initial = [s for s in statuses if s.is_initial]
        assert len(initial) == 1, f"{workflow.code}: needs exactly one initial status"
        assert any(s.is_final for s in statuses), f"{workflow.code}: needs a final status"

        for status in statuses:
            if status.is_final:
                # Only corrections (e.g. cancelling a letter already sent) may leave a final status.
                ordinary = [t.name for t in outgoing[status.id] if not t.is_correction]
                assert not ordinary, f"{workflow.code}: final {status.code} has moves out: {ordinary}"
            else:
                assert outgoing[status.id], f"{workflow.code}: {status.code} is a dead end"

        # Walk the moves from the initial status; every status must be reachable.
        reached, frontier = {initial[0].id}, [initial[0].id]
        while frontier:
            for move in outgoing[frontier.pop()]:
                if move.to_status_id not in reached:
                    reached.add(move.to_status_id)
                    frontier.append(move.to_status_id)
        unreachable = {s.code for s in statuses if s.id not in reached}
        assert not unreachable, f"{workflow.code}: unreachable statuses {unreachable}"


async def _add_test_workflow(session) -> int:
    return (
        await session.execute(
            text(
                "INSERT INTO core.workflows (code, name, start_role_id, reference_prefix) "
                "SELECT 'test_wf', 'Test', id, 'TEST' FROM core.roles WHERE code = 'applicant' RETURNING id"
            )
        )
    ).scalar_one()


# The next two tests write workflow definitions, which only the owner may do (the app
# user can only read them), so they use owner_session.


async def test_database_refuses_a_second_initial_status(owner_session):
    wf = await _add_test_workflow(owner_session)
    await owner_session.execute(
        text("INSERT INTO core.workflow_statuses (workflow_id, code, name, applicant_label, is_initial) VALUES (:wf, 'a', 'A', 'A', true)"),
        {"wf": wf},
    )
    with pytest.raises(IntegrityError):
        await owner_session.execute(
            text("INSERT INTO core.workflow_statuses (workflow_id, code, name, applicant_label, is_initial) VALUES (:wf, 'b', 'B', 'B', true)"),
            {"wf": wf},
        )


async def test_database_refuses_a_move_into_another_workflows_status(owner_session):
    wf = await _add_test_workflow(owner_session)
    own = (
        await owner_session.execute(
            text("INSERT INTO core.workflow_statuses (workflow_id, code, name, applicant_label) VALUES (:wf, 'a', 'A', 'A') RETURNING id"),
            {"wf": wf},
        )
    ).scalar_one()
    etls_approved = await owner_session.scalar(
        select(WorkflowStatus.id)
        .join(Workflow, Workflow.id == WorkflowStatus.workflow_id)
        .where(Workflow.code == "etls_application", WorkflowStatus.code == "approved")
    )
    with pytest.raises(IntegrityError):
        await owner_session.execute(
            text(
                "INSERT INTO core.workflow_transitions "
                "(workflow_id, from_status_id, to_status_id, required_position_id, name) "
                "SELECT :wf, :from_id, :to_id, id, 'cheat' FROM core.positions WHERE code = 'trade_officer'"
            ),
            {"wf": wf, "from_id": own, "to_id": etls_approved},
        )
