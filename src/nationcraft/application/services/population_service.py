"""Population, approval, stability simulation."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nationcraft.core.events import Event, event_bus
from nationcraft.core.extensions import HookRegistry
from nationcraft.infrastructure.db.models import CountryModel
from nationcraft.infrastructure.repositories import ResourceRepository


class PopulationService:
    """Per-tick population growth, consumption, approval drift, unrest."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.resources = ResourceRepository(session)

    async def process_population_tick(self, world_id: int, delta_seconds: int) -> None:
        rows = await self.session.scalars(
            select(CountryModel).where(CountryModel.world_id == world_id)
        )
        for country in rows:
            scale = delta_seconds / 60.0
            # Per-capita consumption rates. Tuned so a starting country
            # with ~5 farms (250 food/min) can sustain roughly 50M
            # people. The previous rates (0.0005 / 0.0007) made a
            # 125M-population country like Japan burn 62,500 food per
            # minute vs. only 200 produced by its 4 farms — every
            # country starved within 2 ticks of joining.
            #
            # New math: 125M * 0.000002 = 250 food/min (vs 200 produced
            # = small deficit that the player must close by building
            # more farms). Water: 125M * 0.000003 = 375/min vs 90 from
            # 3 wells — deficit too, but smaller.
            food_need = country.population * 0.000002 * scale
            water_need = country.population * 0.000003 * scale
            food_have = await self.resources.get_amount(country.id, "food")
            water_have = await self.resources.get_amount(country.id, "water")

            food_eaten = min(food_have, food_need)
            water_drank = min(water_have, water_need)
            if food_eaten:
                await self.resources.adjust(country.id, "food", -food_eaten)
            if water_drank:
                await self.resources.adjust(country.id, "water", -water_drank)

            food_coverage = food_eaten / max(food_need, 1.0)
            water_coverage = water_drank / max(water_need, 1.0)
            coverage = (food_coverage + water_coverage) / 2.0
            approval_delta = (coverage - 0.5) * 2.0 * scale
            country.approval = max(0.0, min(100.0, country.approval + approval_delta))

            growth_rate = (country.approval - 50.0) / 1000.0 * scale
            new_pop = max(0, int(country.population * (1 + growth_rate)))
            if new_pop != country.population:
                country.population = new_pop

            unrest_level = await HookRegistry.instance().invoke(
                "population.unrest", 0.0,
                approval=country.approval, stability=country.stability,
                pollution=country.pollution,
            )
            if unrest_level > 0.7:
                await event_bus.publish(Event(
                    type="population.protest_started", world_id=world_id,
                    payload={"country_id": country.id, "approval": country.approval,
                             "unrest": unrest_level},
                ))

            await event_bus.publish(Event(
                type="population.updated", world_id=world_id,
                payload={"country_id": country.id, "population": country.population,
                         "approval": country.approval},
            ))
        await self.session.flush()
