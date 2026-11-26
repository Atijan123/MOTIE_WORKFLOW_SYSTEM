from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api import health
from app.core.config import settings
from app.core.documents import router as documents
from app.core.identity import router as identity
from app.core.workflow import absence_router, acting_router, delegation_router, signatory_router
from app.core.workflow import router as workflow
from app.core.workflow.service import WorkflowError
from app.db.session import engine
from app.modules.etls import history_router as etls_history
from app.modules.etls import router as etls


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Code before `yield` runs at startup, code after it at shutdown.
    # A misconfigured office server stops here with the reasons, instead of
    # running half-protected (step 13a).
    problems = settings.startup_problems()
    if problems:
        raise RuntimeError("The API can't start:\n  " + "\n  ".join(problems))
    yield
    # Close every pooled database connection cleanly when the server stops.
    await engine.dispose()


app = FastAPI(title="MOTIE Workflow Platform", lifespan=lifespan)

app.include_router(health.router)
app.include_router(identity.router)
app.include_router(workflow.router)
app.include_router(documents.router)
app.include_router(delegation_router.router)
app.include_router(absence_router.router)
app.include_router(acting_router.router)
app.include_router(signatory_router.router)
app.include_router(etls.router)
app.include_router(etls_history.router)
app.add_exception_handler(WorkflowError, workflow.workflow_error_handler)
