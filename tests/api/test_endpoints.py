"""API-level smoke tests using FastAPI TestClient with SQLite override."""
from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from nationcraft.api.app import create_app
from nationcraft.api.dependencies import get_session
from nationcraft.infrastructure.db.models import Base
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


@pytest.fixture
def test_app():
    import os
    os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")

    async def _setup():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    import asyncio
    asyncio.get_event_loop().run_until_complete(_setup())

    maker = async_sessionmaker(bind=engine, expire_on_commit=False, class_=AsyncSession)

    async def override_session():
        async with maker() as s:
            try:
                yield s
                await s.commit()
            except Exception:
                await s.rollback()
                raise

    app = create_app()
    app.dependency_overrides[get_session] = override_session
    return app


@pytest.mark.asyncio
async def test_health_endpoint(test_app) -> None:
    async with AsyncClient(transport=ASGITransport(app=test_app), base_url="http://test") as client:
        r = await client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True


@pytest.mark.asyncio
async def test_register_and_login_flow(test_app) -> None:
    async with AsyncClient(transport=ASGITransport(app=test_app), base_url="http://test") as client:
        # Register
        r = await client.post("/auth/register", json={
            "telegram_id": 999, "password": "password123", "username": "tester", "locale": "en"
        })
        assert r.status_code == 200
        body = r.json()
        assert body["ok"] is True
        token = body["data"]["access_token"]

        # Use token to call /worlds (should return empty list since no worlds seeded).
        r = await client.get("/worlds", headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 200
