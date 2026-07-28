"""Regression tests for bugs fixed in the latest pass.

Covers:
  - The 4 newly added buildings (quarry, electronics_factory, oil_refinery,
    uranium_mine) exist in the game data and produce the previously-deadlocked
    resources (stone, electronics, fuel, uranium).
  - The previously undefined names that ruff F821 flagged are now importable:
      * ``LogoutRequest`` in ``auth_service.py``
      * ``aiohttp`` at module level in ``bot/app.py``
      * ``MarketOrderSide`` in ``domain/repositories/__init__.py``
  - The new API endpoints exist:
      * ``GET /production/buildings/catalog``
      * ``GET /production/research``
      * ``GET /military/units/catalog``
  - ``RedisCache.enabled`` is False when ``REDIS_URL`` is empty.
"""
from __future__ import annotations

import pytest


def test_quarry_produces_stone():
    """quarry was missing — stone was a finite resource (only starting)."""
    from nationcraft.core.config import game_data
    game_data.reload()
    assert "quarry" in game_data.buildings
    q = game_data.buildings["quarry"]
    assert "stone" in q.production
    assert q.production["stone"] > 0


def test_electronics_factory_produces_electronics():
    """electronics_factory was missing — research_center was unbuildable for
    non-Japan players, deadlocking the entire tech tree.
    """
    from nationcraft.core.config import game_data
    game_data.reload()
    assert "electronics_factory" in game_data.buildings
    ef = game_data.buildings["electronics_factory"]
    assert "electronics" in ef.production
    assert ef.production["electronics"] > 0
    # Should NOT require tech (otherwise the chain is still deadlocked).
    assert ef.requires_tech == []


def test_oil_refinery_produces_fuel():
    """oil_refinery was missing — fuel was unobtainable, deadlocking
    all air/naval units (which need fuel for cost + maintenance).
    """
    from nationcraft.core.config import game_data
    game_data.reload()
    assert "oil_refinery" in game_data.buildings
    o = game_data.buildings["oil_refinery"]
    assert "fuel" in o.production
    assert o.production["fuel"] > 0


def test_uranium_mine_produces_uranium():
    """uranium_mine was missing — only 3 countries started with uranium,
    so nuclear power and ICBMs were essentially unbuildable.
    """
    from nationcraft.core.config import game_data
    game_data.reload()
    assert "uranium_mine" in game_data.buildings
    u = game_data.buildings["uranium_mine"]
    assert "uranium" in u.production
    assert u.production["uranium"] > 0


def test_nuclear_power_plant_does_not_require_concrete():
    """nuclear_power_plant previously required ``concrete: 200`` which is
    not a defined resource and has no producer — making it permanently
    unbuildable. Replaced with ``stone: 500`` (stone is producible by quarry).
    """
    from nationcraft.core.config import game_data
    game_data.reload()
    np = game_data.buildings["nuclear_power_plant"]
    assert "concrete" not in np.base_cost, "concrete is not a defined resource"
    # The replacement material should be something producible.
    assert "stone" in np.base_cost


def test_logout_request_importable():
    """F821 fix: ``LogoutRequest`` must be importable from auth_service module."""
    from nationcraft.application.services.auth_service import AuthService  # noqa: F401
    # If the import fails, the test fails.
    # Also verify the annotation is resolvable (it's a string under
    # ``from __future__ import annotations``, so we use typing.get_type_hints).
    import typing
    hints = typing.get_type_hints(AuthService.logout)
    assert "req" in hints


def test_aiohttp_module_level_import():
    """F821 fix: ``aiohttp`` must be importable at module level in bot/app.py
    (previously only imported inside a function, but used in a string
    annotation).
    """
    import nationcraft.bot.app as bot_app
    assert hasattr(bot_app, "aiohttp"), "aiohttp must be module-level in bot.app"


def test_market_order_side_importable():
    """F821 fix: ``MarketOrderSide`` must be importable from domain.repositories."""
    from nationcraft.domain.repositories import IMarketRepository  # noqa: F401
    # If the module imports cleanly, the test passes.
    # Also verify the Protocol's matching_orders signature can be resolved.
    import typing
    hints = typing.get_type_hints(IMarketRepository.matching_orders)
    assert "side" in hints


def test_redis_cache_disabled_when_url_empty(monkeypatch):
    """RedisCache should set ``enabled=False`` when REDIS_URL is empty,
    so callers can fall back to in-memory implementations without trying
    to connect.
    """
    from nationcraft.infrastructure.cache import RedisCache
    cache = RedisCache(url="")
    assert cache.enabled is False
    assert cache._redis is None


def test_redis_cache_enabled_when_url_set():
    from nationcraft.infrastructure.cache import RedisCache
    cache = RedisCache(url="redis://localhost:6379/0")
    assert cache.enabled is True
    assert cache._redis is not None


# ---- API endpoint smoke tests ----

@pytest.fixture
def test_app():
    """FastAPI app with in-memory SQLite (same pattern as tests/api/test_endpoints.py)."""
    import asyncio
    import os
    os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"
    from nationcraft.api.app import create_app
    from nationcraft.api.dependencies import get_session
    from nationcraft.infrastructure.db.models import Base
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")

    async def _setup():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    asyncio.run(_setup())

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
async def test_buildings_catalog_endpoint(test_app):
    """GET /production/buildings/catalog should return all buildable buildings."""
    from httpx import ASGITransport, AsyncClient
    async with AsyncClient(transport=ASGITransport(app=test_app), base_url="http://test") as client:
        # Register a player.
        r = await client.post("/auth/register", json={
            "telegram_id": 999001, "password": "Passw0rd!",
            "username": "regtest", "locale": "en",
        })
        assert r.status_code == 200, r.text
        token = r.json()["data"]["access_token"]
        h = {"Authorization": f"Bearer {token}"}

        # Catalog endpoint only needs auth, not a country.
        r = await client.get("/production/buildings/catalog", headers=h)
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["ok"] is True
        keys = {b["key"] for b in data["data"]}
        # Verify the 4 new buildings are in the catalog.
        for expected in ("quarry", "electronics_factory", "oil_refinery", "uranium_mine"):
            assert expected in keys, f"missing {expected} in catalog"


@pytest.mark.asyncio
async def test_research_catalog_endpoint_returns_400_without_country(test_app):
    """GET /production/research requires a country; without one it returns
    400 (game_rule_violation) — NOT 404/405. This proves the endpoint exists.
    """
    from httpx import ASGITransport, AsyncClient
    async with AsyncClient(transport=ASGITransport(app=test_app), base_url="http://test") as client:
        r = await client.post("/auth/register", json={
            "telegram_id": 999002, "password": "Passw0rd!",
            "username": "regtest2", "locale": "en",
        })
        token = r.json()["data"]["access_token"]
        h = {"Authorization": f"Bearer {token}"}

        r = await client.get("/production/research", headers=h)
        # 400 = endpoint exists but player has no country yet.
        assert r.status_code == 400, r.text
        body = r.json()
        assert body["ok"] is False
        assert body["error"]["code"] == "game_rule_violation"


@pytest.mark.asyncio
async def test_units_catalog_endpoint(test_app):
    """GET /military/units/catalog should return all trainable units."""
    from httpx import ASGITransport, AsyncClient
    async with AsyncClient(transport=ASGITransport(app=test_app), base_url="http://test") as client:
        r = await client.post("/auth/register", json={
            "telegram_id": 999003, "password": "Passw0rd!",
            "username": "regtest3", "locale": "en",
        })
        token = r.json()["data"]["access_token"]
        h = {"Authorization": f"Bearer {token}"}

        r = await client.get("/military/units/catalog", headers=h)
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["ok"] is True
        keys = {u["key"] for u in data["data"]}
        assert "infantry" in keys
        assert "tank" in keys
