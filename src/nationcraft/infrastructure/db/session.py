"""Database session management (async SQLAlchemy 2.x)."""
from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from nationcraft.core.config import settings


def _build_engine() -> AsyncEngine:
    """Build the async engine, conditionally applying pool kwargs.

    SQLite (memory or file) does not accept QueuePool args, so we skip
    them for SQLite URLs.
    """
    url = settings.DATABASE_URL
    kwargs: dict = {"echo": settings.is_dev}
    if not url.startswith("sqlite"):
        kwargs.update(
            pool_size=settings.DB_POOL_SIZE,
            max_overflow=settings.DB_MAX_OVERFLOW,
            pool_timeout=settings.DB_POOL_TIMEOUT,
            pool_pre_ping=True,
        )
    return create_async_engine(url, **kwargs)


engine: AsyncEngine = _build_engine()

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    expire_on_commit=False,
    class_=AsyncSession,
    autoflush=False,
)


@asynccontextmanager
async def session_scope() -> AsyncIterator[AsyncSession]:
    """Context-managed session that commits on success, rolls back on error."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def dispose() -> None:
    await engine.dispose()
