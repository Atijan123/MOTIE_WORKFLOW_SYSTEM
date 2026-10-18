from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api import health
from app.db.session import engine


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Code before `yield` runs at startup, code after it at shutdown.
    yield
    # Close every pooled database connection cleanly when the server stops.
    await engine.dispose()


app = FastAPI(title="MOTIE Workflow Platform", lifespan=lifespan)

app.include_router(health.router)
