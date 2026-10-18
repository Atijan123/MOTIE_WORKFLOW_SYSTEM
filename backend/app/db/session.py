from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings

# One engine per process. It owns the connection pool; sessions borrow connections from it.
# pool_pre_ping checks a pooled connection is still alive before handing it out
# (e.g. after Postgres restarts).
engine = create_async_engine(settings.database_url, pool_pre_ping=True)

SessionLocal = async_sessionmaker(engine, expire_on_commit=False)


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency: one session per request, closed when the request ends."""
    async with SessionLocal() as session:
        yield session
