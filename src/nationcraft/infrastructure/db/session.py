"""Database session management (async SQLAlchemy 2.x)."""
from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator

from sqlalchemy import event
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
    them for SQLite URLs. For SQLite we also install an event listener
    that runs ``PRAGMA journal_mode=WAL``, ``PRAGMA busy_timeout=5000``,
    and ``PRAGMA synchronous=NORMAL`` on every new connection.

    The default SQLite journal mode (``delete``) holds an exclusive lock
    during writes, which means the API's reads block on the tick engine's
    writes — and on a busy tick engine that can take seconds. WAL mode
    allows concurrent readers + one writer, and ``busy_timeout=5000``
    makes locked-write attempts wait up to 5s before raising
    "database is locked" instead of failing immediately.
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
    engine = create_async_engine(url, **kwargs)

    if url.startswith("sqlite"):
        # Install SQLite PRAGMAs on every new connection.
        # WAL mode: readers don't block writers (and vice versa) — crucial
        # for the --local mode where API + worker + bot share one process.
        # busy_timeout: writers wait up to 5s for a lock instead of
        # failing immediately.
        # synchronous=NORMAL: durable enough for a single-node dev game,
        # much faster than FULL (the default).
        @event.listens_for(engine.sync_engine, "connect")
        def _sqlite_pragmas(dbapi_conn, _record):  # type: ignore[no-untyped-def]
            cursor = dbapi_conn.cursor()
            try:
                cursor.execute("PRAGMA journal_mode=WAL")
                cursor.execute("PRAGMA busy_timeout=5000")
                cursor.execute("PRAGMA synchronous=NORMAL")
                cursor.execute("PRAGMA foreign_keys=ON")
            finally:
                cursor.close()

    return engine


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
