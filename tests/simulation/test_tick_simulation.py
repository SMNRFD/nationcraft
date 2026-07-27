"""Simulation test — runs multiple ticks end-to-end."""
from __future__ import annotations

import asyncio

import pytest

from nationcraft.application.services import (
    CountryService,
    ProductionService,
    WorldService,
    register_default_handlers,
)
from nationcraft.core.config import game_data
from nationcraft.core.tick import TickContext, tick_engine
from nationcraft.infrastructure.db.models import PlayerModel


@pytest.fixture(autouse=True)
def _load_game_data():
    game_data.reload()


@pytest.mark.asyncio
async def test_simulation_runs_multiple_ticks(session) -> None:
    register_default_handlers()
    ws = WorldService(session)
    await ws.ensure_worlds(capacity=100)
    player = PlayerModel(telegram_id=1, username="sim", locale="en", role="player")
    session.add(player)
    await session.flush()
    cs = CountryService(session)
    country = await cs.select_country(player_id=player.id, world_id=1, country_code="IR")
    await session.commit()

    # Run 3 ticks against the engine manually (skip scheduler).
    for i in range(3):
        ctx = TickContext(world_id=1, tick=i + 1)
        await tick_engine.run(ctx)
        await session.commit()

    # The country should still exist and have a sensible state.
    c = await cs.get_country(country.id)
    assert c.population > 0
