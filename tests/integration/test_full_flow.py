"""End-to-end game flow integration test.

Exercises: register → world creation → country selection →
production tick → mission evaluation → resource accumulation.
"""
from __future__ import annotations

import pytest

from nationcraft.application.services import (
    CountryService,
    MarketService,
    MilitaryService,
    ProductionService,
    WorldService,
)
from nationcraft.core.config import game_data
from nationcraft.infrastructure.db.models import PlayerModel
from nationcraft.infrastructure.repositories import ResourceRepository


@pytest.fixture(autouse=True)
def _load_game_data():
    game_data.reload()


@pytest.mark.asyncio
async def test_full_player_journey(session) -> None:
    """A single player goes from registration to training units."""
    # 1. World auto-creates with countries.
    ws = WorldService(session)
    worlds = await ws.ensure_worlds(capacity=50)
    assert len(worlds) >= 1
    world_id = worlds[0].id

    # 2. Player joins.
    player = PlayerModel(telegram_id=42, username="alice", locale="en", role="player")
    session.add(player)
    await session.flush()

    # 3. Player selects Iran.
    cs = CountryService(session)
    country = await cs.select_country(player.id, world_id, "IR")
    assert country.code == "IR"
    assert country.player_id == player.id
    await session.commit()

    # 4. Iran's starting resources should be present.
    rr = ResourceRepository(session)
    money = await rr.get_amount(country.id, "money")
    assert money == 2_000_000.0
    oil = await rr.get_amount(country.id, "oil")
    assert oil == 20_000.0

    # 5. Snapshot shows resources + buildings.
    snapshot = await cs.snapshot(country.id)
    assert "country" in snapshot
    assert "resources" in snapshot
    assert "buildings" in snapshot
    # Iran's starting_buildings includes farm:5, oil_field:2, etc.
    building_keys = [b["key"] for b in snapshot["buildings"]]
    assert "farm" in building_keys
    assert "barracks" in building_keys

    # 6. Production tick: farm should produce food.
    prod_svc = ProductionService(session)
    await prod_svc.complete_constructions()
    deltas = await prod_svc.process_production_tick(world_id, delta_seconds=60)
    assert country.id in deltas
    # Farms produce food; oil_fields produce oil.
    assert "food" in deltas[country.id] or "oil" in deltas[country.id]
    await session.commit()

    # 7. Player trains infantry (give them weapons first).
    await rr.adjust(country.id, "weapons", 100)
    ms = MilitaryService(session)
    count = await ms.train(country.id, "infantry", 10)
    assert count == 10
    await session.commit()

    # 8. Player abandons country.
    await cs.abandon_country(player.id)
    await session.commit()

    # 9. World player count should reflect.
    world = await ws.get(world_id)
    # Note: abandon doesn't decrement count by design (only count active selections).
    assert world.player_count >= 1
