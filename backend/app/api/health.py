import logging

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_session

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/health", tags=["health"])


@router.get("")
async def health():
    """Liveness: the API process is running. Never touches the database."""
    return {"status": "ok"}


@router.get("/db")
async def health_db(session: AsyncSession = Depends(get_session)):
    """Readiness: the API can reach Postgres and run a query."""
    try:
        # SELECT 1 asks Postgres to return the number 1. It reads no tables;
        # it only proves we can open a connection and get an answer back.
        await session.execute(text("SELECT 1"))
    except Exception:
        # The full error goes to the server log for whoever operates the system.
        # The caller only learns that the database is down: the raw error text can
        # reveal the database host and username. 503 means "temporarily unavailable,
        # retry later", which is what a monitoring tool should hear.
        logger.exception("Database health check failed")
        return JSONResponse(status_code=503, content={"database": "unavailable"})
    return {"database": "ok"}
