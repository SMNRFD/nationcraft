"""Pytest fixtures shared across the suite."""
from __future__ import annotations

import asyncio
import os
from typing import AsyncIterator

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

# Configure test environment BEFORE importing nationcraft modules.
# We FORCE-set (not setdefault) so that any DATABASE_URL exported in the
# surrounding shell — e.g. ``DATABASE_URL=file:/somewhere/custom.db`` —
# cannot leak into the test suite and cause confusing failures
# (the production engine is built at import time and would otherwise
# try to connect to whatever the shell said, breaking every test).
os.environ["ENV"] = "test"
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"
os.environ["REDIS_URL"] = "redis://localhost:6379/15"
os.environ["SECRET_KEY"] = "test-secret-only-32-bytes-padding!!"
os.environ["TELEGRAM_BOT_TOKEN"] = "0:test"

from nationcraft.infrastructure.db.models import Base  # noqa: E402


@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture
async def engine():
    eng = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield eng
    await eng.dispose()


@pytest_asyncio.fixture
async def session(engine) -> AsyncIterator[AsyncSession]:
    maker = async_sessionmaker(bind=engine, expire_on_commit=False, class_=AsyncSession)
    async with maker() as s:
        yield s
