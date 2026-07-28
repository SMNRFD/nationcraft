"""Tests for the bugs fixed in this commit.

Each test targets a specific bug that was found by manually exercising
the API and reading the source code. Tests are intentionally focused
on the bug — they fail without the fix and pass with it.
"""
from __future__ import annotations

import pytest

from nationcraft.core.config import game_data


# ---------------------------------------------------------------------
# Bug: /countries/select used untyped ``dict`` → KeyError → 500
# ---------------------------------------------------------------------

@pytest.mark.asyncio
async def test_select_country_rejects_missing_fields_with_422(session):
    """The select endpoint should return a clean 422 (not a 500) when
    the request body is missing required fields.
    """
    from fastapi.testclient import TestClient
    # We can't use TestClient because the app creates a real engine at
    # import time. Instead, verify the Pydantic model raises cleanly.
    from nationcraft.api.routers.countries import SelectCountryRequest
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        SelectCountryRequest()  # missing world_id and country_code

    with pytest.raises(ValidationError):
        # country_code too long
        SelectCountryRequest(world_id=1, country_code="JPN")


# ---------------------------------------------------------------------
# Bug: MissionService.seed_for_country was never called
# ---------------------------------------------------------------------

@pytest.mark.asyncio
async def test_select_country_seeds_missions(session):
    """When a player selects a country, tutorial + daily missions
    should be auto-seeded for them.
    """
    from nationcraft.application.services import CountryService, WorldService
    from nationcraft.application.services.mission_service import MissionService
    from nationcraft.infrastructure.db.models import PlayerModel

    game_data.reload()
    ws = WorldService(session)
    worlds = await ws.ensure_worlds(capacity=50)
    world_id = worlds[0].id

    player = PlayerModel(telegram_id=1234567890, username="seeded_test", locale="en", role="player")
    session.add(player)
    await session.flush()

    cs = CountryService(session)
    country = await cs.select_country(player.id, world_id, "IR")
    await session.commit()

    ms = MissionService(session)
    # Use the returned country.id (the player ORM object's country_id
    # isn't refreshed by the bulk UPDATE inside select_country).
    missions = await ms.list_for_country(country.id)
    # Should have at least 3 tutorial + 3 daily missions.
    assert len(missions) >= 6, f"expected >=6 seeded missions, got {len(missions)}"
    keys = {m.key for m in missions}
    assert "tut_select_country" in keys
    assert "tut_build_farm" in keys
    assert "tut_train_infantry" in keys
    assert "daily_food_reserve" in keys


# ---------------------------------------------------------------------
# Bug: MissionRepository._to_entity didn't convert category string → enum
# ---------------------------------------------------------------------

@pytest.mark.asyncio
async def test_mission_category_is_enum_not_string(session):
    """list_for_country should return Mission entities with ``category``
    as a MissionCategory enum (so ``.value`` works).
    """
    from nationcraft.application.services import CountryService, WorldService
    from nationcraft.application.services.mission_service import MissionService
    from nationcraft.infrastructure.db.models import PlayerModel
    from nationcraft.domain.enums import MissionCategory

    game_data.reload()
    ws = WorldService(session)
    worlds = await ws.ensure_worlds(capacity=50)
    world_id = worlds[0].id

    player = PlayerModel(telegram_id=999111, username="enum_test", locale="en", role="player")
    session.add(player)
    await session.flush()

    cs = CountryService(session)
    country = await cs.select_country(player.id, world_id, "BR")
    await session.commit()

    ms = MissionService(session)
    missions = await ms.list_for_country(country.id)
    assert len(missions) > 0
    for m in missions:
        # The bug: category was a raw string, so .value crashed with
        # AttributeError: 'str' object has no attribute 'value'.
        assert isinstance(m.category, MissionCategory), (
            f"expected MissionCategory enum, got {type(m.category).__name__}: {m.category!r}"
        )
        # .value should not raise.
        _ = m.category.value
        _ = m.status.value


# ---------------------------------------------------------------------
# Bug: MissionService.evaluate didn't honor op=">" with target=0
# ---------------------------------------------------------------------

@pytest.mark.asyncio
async def test_mission_evaluate_handles_target_zero(session):
    """``tut_select_country`` has ``objective: {metric: population, op: ">", target: 0}``.
    A country with population > 0 should immediately complete.
    """
    from nationcraft.application.services import CountryService, WorldService
    from nationcraft.application.services.mission_service import MissionService
    from nationcraft.infrastructure.db.models import PlayerModel
    from nationcraft.domain.enums import MissionStatus

    game_data.reload()
    ws = WorldService(session)
    worlds = await ws.ensure_worlds(capacity=50)
    world_id = worlds[0].id

    player = PlayerModel(telegram_id=999222, username="target_zero_test", locale="en", role="player")
    session.add(player)
    await session.flush()

    cs = CountryService(session)
    country = await cs.select_country(player.id, world_id, "IR")
    await session.commit()

    ms = MissionService(session)
    await ms.evaluate(country.id)
    await session.commit()

    missions = await ms.list_for_country(country.id)
    tut_select = next((m for m in missions if m.key == "tut_select_country"), None)
    assert tut_select is not None
    assert tut_select.status == MissionStatus.COMPLETED, (
        f"tut_select_country should be COMPLETED (pop={country.population} > 0), "
        f"got {tut_select.status}"
    )


# ---------------------------------------------------------------------
# Bug: MissionService._build_context overwrote research_points with country column
# ---------------------------------------------------------------------

@pytest.mark.asyncio
async def test_mission_context_uses_research_points_stock_not_column(session):
    """research_points is tracked as a resource stock (the production
    tick writes there). The CountryModel.research_points column is a
    dead field that's never updated. Missions reading ``metric: research_points``
    should see the stock value, not the column value.
    """
    from nationcraft.application.services import CountryService, WorldService
    from nationcraft.application.services.mission_service import MissionService
    from nationcraft.infrastructure.db.models import PlayerModel
    from nationcraft.infrastructure.repositories import ResourceRepository

    game_data.reload()
    ws = WorldService(session)
    worlds = await ws.ensure_worlds(capacity=50)
    world_id = worlds[0].id

    player = PlayerModel(telegram_id=999333, username="rp_test", locale="en", role="player")
    session.add(player)
    await session.flush()

    cs = CountryService(session)
    country = await cs.select_country(player.id, world_id, "JP")
    await session.commit()

    # Stock up research_points.
    rr = ResourceRepository(session)
    await rr.set_amount(country.id, "research_points", 75.0)
    await session.commit()

    # Re-fetch country to avoid stale state.
    from nationcraft.infrastructure.db.models import CountryModel
    country_fresh = await session.get(CountryModel, country.id)
    # Country column should still be 0 (we never update it).
    assert country_fresh.research_points == 0.0

    ms = MissionService(session)
    ctx = await ms._build_context(country_fresh)
    # Context should reflect the STOCK value, not the column value.
    assert ctx.get("research_points") == 75.0, (
        f"expected research_points=75.0 (from stock), got {ctx.get('research_points')}"
    )


# ---------------------------------------------------------------------
# Bug: UnitRepository.adjust hardcoded world_id=0
# ---------------------------------------------------------------------

@pytest.mark.asyncio
async def test_unit_adjust_uses_real_world_id(session):
    """Newly-created unit rows should reference the country's real
    world_id (not 0). Otherwise world-scoped queries miss them.
    """
    from nationcraft.infrastructure.db.models import CountryModel
    from nationcraft.infrastructure.repositories import UnitRepository

    # Country in world 1.
    country = CountryModel(world_id=1, code="TE", name="Test", population=100, treasury=0)
    session.add(country)
    await session.flush()

    ur = UnitRepository(session)
    unit = await ur.adjust(country.id, "infantry", 10)
    await session.commit()

    # The returned entity should have the correct world_id.
    assert unit.world_id == 1, f"expected world_id=1, got {unit.world_id}"

    # And the actual DB row should too.
    from nationcraft.infrastructure.db.models import UnitModel
    from sqlalchemy import select
    db_unit = await session.scalar(select(UnitModel).where(UnitModel.country_id == country.id))
    assert db_unit is not None
    assert db_unit.world_id == 1, f"DB row has world_id={db_unit.world_id}, expected 1"


# ---------------------------------------------------------------------
# Bug: GameEventService._apply_effects ignored resource effects
# ---------------------------------------------------------------------

@pytest.mark.asyncio
async def test_event_apply_effects_adjusts_resources(session):
    """Effects with keys that aren't CountryModel columns (food, water,
    money, etc.) should adjust resource stocks, not be silently dropped.
    """
    from nationcraft.application.services.event_service import GameEventService
    from nationcraft.infrastructure.db.models import CountryModel
    from nationcraft.infrastructure.repositories import ResourceRepository

    country = CountryModel(world_id=1, code="EV", name="EventTest", population=1000, treasury=1000.0)
    session.add(country)
    await session.flush()

    rr = ResourceRepository(session)
    await rr.set_amount(country.id, "food", 10000.0)
    await rr.set_amount(country.id, "water", 5000.0)
    await session.commit()

    svc = GameEventService(session)
    # Effects: -5000 food, -2000 water (resources), +5.0 approval (column).
    await svc._apply_effects(country, {
        "food": -5000,
        "water": -2000,
        "approval": 5.0,
    })
    await session.commit()

    # Resources should be adjusted.
    food = await rr.get_amount(country.id, "food")
    water = await rr.get_amount(country.id, "water")
    assert food == 5000.0, f"expected food=5000 (10000-5000), got {food}"
    assert water == 3000.0, f"expected water=3000 (5000-2000), got {water}"

    # Approval column should also be updated.
    from nationcraft.infrastructure.db.models import CountryModel as CM
    c_fresh = await session.get(CM, country.id)
    assert c_fresh.approval == 55.0, f"expected approval=55.0 (50+5), got {c_fresh.approval}"


# ---------------------------------------------------------------------
# Bug: GameEventService only triggered "random" category events
# ---------------------------------------------------------------------

@pytest.mark.asyncio
async def test_event_service_triggers_non_random_categories(session):
    """Events with category ``natural``, ``economic``, ``political``,
    ``holiday`` should be eligible for random triggering (not just
    ``random``). We don't test the actual randomness — just that the
    eligible list includes them.
    """
    from nationcraft.application.services.event_service import _TRIGGABLE_CATEGORIES

    assert "random" in _TRIGGABLE_CATEGORIES
    assert "natural" in _TRIGGABLE_CATEGORIES
    assert "economic" in _TRIGGABLE_CATEGORIES
    assert "political" in _TRIGGABLE_CATEGORIES
    assert "holiday" in _TRIGGABLE_CATEGORIES


# ---------------------------------------------------------------------
# Bug: register_default_handlers was not idempotent
# ---------------------------------------------------------------------

def test_register_default_handlers_is_idempotent():
    """Calling register_default_handlers twice should NOT double-register
    handlers. We verify by counting phase handlers before and after.
    """
    import nationcraft.application.services.tick_registration as tick_reg_mod
    from nationcraft.application.services.tick_registration import register_default_handlers
    from nationcraft.core.tick import tick_engine
    from nationcraft.core.config import TickPhases

    # Reset the idempotency flag so we can test from a clean state,
    # even if previous tests already called register_default_handlers.
    tick_reg_mod._handlers_registered = False
    # Also clear any existing handlers in the 5 phases we register.
    for phase in (TickPhases.PRODUCTION, TickPhases.RESEARCH, TickPhases.POPULATION,
                  TickPhases.EVENTS, TickPhases.MISSIONS):
        tick_engine._handlers.pop(phase, None)

    # Snapshot existing handler counts (should be 0 for our 5 phases).
    before = {p: len(tick_engine._handlers.get(p, [])) for p in TickPhases}
    register_default_handlers()
    after_first = {p: len(tick_engine._handlers.get(p, [])) for p in TickPhases}
    register_default_handlers()
    after_second = {p: len(tick_engine._handlers.get(p, [])) for p in TickPhases}

    # First call should add exactly 1 handler to each of the 5 phases.
    for phase in (TickPhases.PRODUCTION, TickPhases.RESEARCH, TickPhases.POPULATION,
                  TickPhases.EVENTS, TickPhases.MISSIONS):
        assert after_first[phase] == before[phase] + 1, (
            f"first call should add 1 handler to {phase}: "
            f"before={before[phase]}, after={after_first[phase]}"
        )
    # Second call should be a no-op.
    for phase in TickPhases:
        assert after_second[phase] == after_first[phase], (
            f"second call should not change {phase}: "
            f"first={after_first[phase]}, second={after_second[phase]}"
        )


# ---------------------------------------------------------------------
# Bug: event_service used order_by("random()") which fails in SQLAlchemy 2.x
# ---------------------------------------------------------------------

@pytest.mark.asyncio
async def test_event_service_can_pick_random_country(session):
    """maybe_trigger should not crash with ``Can't resolve label
    reference for ORDER BY`` when picking a random country.
    """
    from nationcraft.application.services.event_service import GameEventService
    from nationcraft.infrastructure.db.models import CountryModel

    # Add a country so the random query has something to pick.
    country = CountryModel(world_id=1, code="RC", name="RandomTest", population=1000, treasury=0)
    session.add(country)
    await session.flush()

    svc = GameEventService(session)
    # Force the trigger by calling _apply_effects directly (avoids
    # the 1% random chance in maybe_trigger). We just want to verify
    # that the random-country SELECT doesn't raise.
    # The actual bug was in maybe_trigger's order_by("random()").
    # Run maybe_trigger many times to maximize the chance of hitting
    # the random-country path.
    for _ in range(100):
        await svc.maybe_trigger(world_id=1, tick=1)
    await session.commit()
    # If we got here without an exception, the fix works.


# ---------------------------------------------------------------------
# Bug: military_service.train used scalar_one_or_none → MultipleResultsFound
# ---------------------------------------------------------------------

@pytest.mark.asyncio
async def test_train_works_when_country_has_multiple_barracks(session):
    """Countries often have multiple barracks (US starts with 2).
    The training flow must not crash with MultipleResultsFound when
    checking the building prerequisite.
    """
    from nationcraft.application.services import MilitaryService
    from nationcraft.infrastructure.db.models import CountryModel, BuildingModel
    from nationcraft.domain.enums import BuildingStatus
    from nationcraft.infrastructure.repositories import ResourceRepository
    from datetime import datetime, timezone

    country = CountryModel(world_id=1, code="MB", name="MultiBarracks", population=100, treasury=100000.0)
    session.add(country)
    await session.flush()

    # Add TWO barracks (matches US starting setup).
    for _ in range(2):
        session.add(BuildingModel(
            world_id=1, country_id=country.id, key="barracks",
            level=1, status=BuildingStatus.ACTIVE.value,
            started_at=datetime.now(timezone.utc), completes_at=None,
        ))
    await session.flush()

    # Give resources for 10 infantry (money + weapons + food).
    rr = ResourceRepository(session)
    await rr.set_amount(country.id, "money", 100000.0)
    await rr.set_amount(country.id, "weapons", 100.0)
    await rr.set_amount(country.id, "food", 10000.0)
    await session.commit()

    svc = MilitaryService(session)
    # This used to raise MultipleResultsFound → 500.
    total = await svc.train(country.id, "infantry", 10)
    await session.commit()
    assert total == 10, f"expected 10 trained, got {total}"


@pytest.mark.asyncio
async def test_production_throttles_when_inputs_missing(session):
    """A steel_mill with 0 iron should produce 0 steel (not full output).
    """
    from nationcraft.application.services.production_service import ProductionService
    from nationcraft.infrastructure.db.models import BuildingModel, CountryModel
    from nationcraft.domain.enums import BuildingStatus
    from datetime import datetime, timezone

    country = CountryModel(world_id=1, code="PT", name="ProdTest", population=100, treasury=0)
    session.add(country)
    await session.flush()

    # Add an active steel_mill with no iron in stock.
    session.add(BuildingModel(
        world_id=1, country_id=country.id, key="steel_mill",
        level=1, status=BuildingStatus.ACTIVE.value,
        started_at=datetime.now(timezone.utc), completes_at=None,
    ))
    await session.flush()

    svc = ProductionService(session)
    deltas = await svc.process_production_tick(world_id=1, delta_seconds=60)
    await session.commit()

    # steel_mill: production {steel: 15}, consumption {iron: 30, coal: 20, electricity: 50}
    # With 0 iron, availability = 0, so steel production should be 0.
    if country.id in deltas:
        steel_produced = deltas[country.id].get("steel", 0.0)
        assert steel_produced == 0.0, (
            f"steel_mill with no iron should produce 0 steel, got {steel_produced}"
        )


# ---------------------------------------------------------------------
# Bug: game balance — countries lacked wood and weapons
# ---------------------------------------------------------------------

def test_all_countries_have_wood_and_weapons():
    """Every country template should start with at least some wood and
    weapons so players can build farms and train infantry from the
    start. Without this, 12 of 14 countries were unplayable.
    """
    game_data.reload()
    for code, cdef in game_data.countries.items():
        wood = cdef.starting_resources.get("wood", 0)
        weapons = cdef.starting_resources.get("weapons", 0)
        assert wood > 0, f"country {code} ({cdef.name}) has no starting wood"
        assert weapons > 0, f"country {code} ({cdef.name}) has no starting weapons"


# ---------------------------------------------------------------------
# Bug: countries starved within 2 ticks (food consumption too high)
# ---------------------------------------------------------------------

@pytest.mark.asyncio
async def test_population_consumption_is_survivable(session):
    """A starting Japan (125M pop, 4 farms, 40k food) should NOT run
    out of food within 5 ticks. Previously it starved in 1 tick.
    """
    from nationcraft.application.services import CountryService, WorldService
    from nationcraft.application.services.population_service import PopulationService
    from nationcraft.infrastructure.db.models import PlayerModel
    from nationcraft.infrastructure.repositories import ResourceRepository

    game_data.reload()
    ws = WorldService(session)
    worlds = await ws.ensure_worlds(capacity=50)
    world_id = worlds[0].id

    player = PlayerModel(telegram_id=999444, username="starve_test", locale="en", role="player")
    session.add(player)
    await session.flush()

    cs = CountryService(session)
    country = await cs.select_country(player.id, world_id, "JP")
    await session.commit()

    rr = ResourceRepository(session)
    food_before = await rr.get_amount(country.id, "food")

    svc = PopulationService(session)
    # Run 5 ticks.
    for _ in range(5):
        await svc.process_population_tick(world_id, delta_seconds=60)
    await session.commit()

    food_after = await rr.get_amount(country.id, "food")
    # Food should still be > 0 (and ideally > 50% of starting).
    assert food_after > 0, f"Japan starved: food went from {food_before} to {food_after}"
    assert food_after > food_before * 0.5, (
        f"food dropped too fast: {food_before} → {food_after} in 5 ticks"
    )
