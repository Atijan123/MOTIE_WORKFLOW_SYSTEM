from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api import health
from app.core.identity import router as identity
from app.core.workflow import absence_router, delegation_router
from app.core.workflow import router as workflow
from app.core.workflow.service import WorkflowError
from app.db.session import engine


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Code before `yield` runs at startup, code after it at shutdown.
    yield
    # Close every pooled database connection cleanly when the server stops.
    await engine.dispose()


app = FastAPI(title="MOTIE Workflow Platform", lifespan=lifespan)

app.include_router(health.router)
app.include_router(identity.router)
app.include_router(workflow.router)
app.include_router(delegation_router.router)
app.include_router(absence_router.router)
app.add_exception_handler(WorkflowError, workflow.workflow_error_handler)
