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
    assert len(statuses) == 6
    # Guards against a misspelt code in the seed: that row would be skipped silently.
    # 7 seeded in 0005, minus the PS placeholder move removed in 0011.
    assert len(transitions) == 6


async def test_every_workflow_is_well_formed(db_session):
    for workflow in (await db_session.scalars(select(Workflow))).all():
        statuses, transitions = await _definition(db_session, workflow)
        outgoing = {s.id: [t for t in transitions if t.from_status_id == s.id] for s in statuses}

        initial = [s for s in statuses if s.is_initial]
        assert len(initial) == 1, f"{workflow.code}: needs exactly one initial status"
        assert any(s.is_final for s in statuses), f"{workflow.code}: needs a final status"

        for status in statuses:
            if status.is_final:
                assert not outgoing[status.id], f"{workflow.code}: final {status.code} has moves out"
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
                "INSERT INTO core.workflows (code, name, start_role_id) "
                "SELECT 'test_wf', 'Test', id FROM core.roles WHERE code = 'applicant' RETURNING id"
            )
        )
    ).scalar_one()


# The next two tests write workflow definitions, which only the owner may do (the app
# user can only read them), so they use owner_session.


async def test_database_refuses_a_second_initial_status(owner_session):
    wf = await _add_test_workflow(owner_session)
    await owner_session.execute(
        text("INSERT INTO core.workflow_statuses (workflow_id, code, name, is_initial) VALUES (:wf, 'a', 'A', true)"),
        {"wf": wf},
    )
    with pytest.raises(IntegrityError):
        await owner_session.execute(
            text("INSERT INTO core.workflow_statuses (workflow_id, code, name, is_initial) VALUES (:wf, 'b', 'B', true)"),
            {"wf": wf},
        )


async def test_database_refuses_a_move_into_another_workflows_status(owner_session):
    wf = await _add_test_workflow(owner_session)
    own = (
        await owner_session.execute(
            text("INSERT INTO core.workflow_statuses (workflow_id, code, name) VALUES (:wf, 'a', 'A') RETURNING id"),
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
