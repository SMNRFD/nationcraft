"""Integration tests for WorldService & CountryService."""
from __future__ import annotations

import pytest

from nationcraft.application.services import CountryService, WorldService
from nationcraft.core.config import game_data
from nationcraft.infrastructure.db.models import PlayerModel


@pytest.fixture(autouse=True)
def _load_game_data():
    game_data.reload()


@pytest.mark.asyncio
async def test_ensure_worlds_creates_first(session) -> None:
    ws = WorldService(session)
    rows = await ws.ensure_worlds(capacity=10)
    assert len(rows) >= 1
    # Should have seeded countries from game_data.
    from nationcraft.infrastructure.db.models import CountryModel
    from sqlalchemy import select
    countries = (await session.execute(select(CountryModel))).scalars().all()
    assert len(countries) == len(game_data.countries)


@pytest.mark.asyncio
async def test_select_and_abandon_country(session) -> None:
    ws = WorldService(session)
    await ws.ensure_worlds(capacity=10)
    await session.commit()
    player = PlayerModel(telegram_id=10, username="bob", locale="en", role="player")
    session.add(player)
    await session.flush()
    cs = CountryService(session)
    country = await cs.select_country(player_id=player.id, world_id=1, country_code="IR")
    await session.commit()
    assert country.code == "IR"
    assert country.player_id == player.id

    # World player count incremented.
    world = await ws.get(1)
    assert world.player_count == 1

    # Abandon.
    await cs.abandon_country(player.id)
    await session.commit()
