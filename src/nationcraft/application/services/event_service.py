"""Game events: trigger configurable random/scheduled events."""
from __future__ import annotations

import random
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from nationcraft.core.config import game_data
from nationcraft.core.events import Event, event_bus
from nationcraft.infrastructure.db.models import CountryModel, GameEventModel
from nationcraft.infrastructure.repositories import GameEventRepository, ResourceRepository


# Effects that target a column on ``CountryModel`` directly (rather
# than a row in ``resource_stocks``). Anything not in this set is
# treated as a resource adjustment.
_COUNTRY_ATTR_EFFECTS = frozenset({
    "population", "treasury", "debt", "approval", "stability",
    "corruption", "education", "healthcare", "electricity_balance",
    "water_balance", "housing_capacity", "pollution", "research_points",
})

# Event categories eligible for random per-tick rolling.
# Previously this only included ``"random"`` — which meant 10 of the 11
# shipped events (drought, earthquake, pandemic, oil_boom, etc., all
# categorized as ``natural``/``economic``/``political``/``holiday``)
# could NEVER fire. Now any non-scheduled category is eligible.
_TRIGGABLE_CATEGORIES = frozenset({
    "random", "natural", "economic", "political", "holiday",
})


class GameEventService:
    """Per-tick event triggering (weighted random sampling)."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = GameEventRepository(session)
        self.resources = ResourceRepository(session)

    async def maybe_trigger(self, world_id: int, tick: int) -> int:
        """Roll for random events. Returns the number triggered."""
        eligible = [
            ev for ev in game_data.events.values()
            if ev.category in _TRIGGABLE_CATEGORIES and tick >= ev.min_world_age_ticks
        ]
        if not eligible:
            return 0
        count = 0
        for ev in eligible:
            # 1% base chance per tick, scaled by event weight.
            if random.random() < 0.01 * ev.weight:
                # Apply effects to a random country in the world.
                # Use ``func.random()`` (not the string ``"random()"``)
                # — SQLAlchemy 2.x rejects textual ORDER BY labels and
                # raises ``Can't resolve label reference for ORDER BY``
                # which made every event-trigger roll crash silently.
                country = await self.session.scalar(
                    select(CountryModel)
                    .where(CountryModel.world_id == world_id)
                    .order_by(func.random())
                    .limit(1)
                )
                if country is None:
                    continue
                await self.repo.create(
                    world_id=world_id, key=ev.key, category=ev.category,
                    payload={"country_id": country.id, "effects": ev.effects},
                    triggered_at=datetime.now(timezone.utc),
                )
                await self._apply_effects(country, ev.effects)
                await event_bus.publish(Event(
                    type="event.triggered", world_id=world_id,
                    payload={"key": ev.key, "country_id": country.id},
                ))
                count += 1
        return count

    async def _apply_effects(self, country: CountryModel, effects: dict) -> None:
        """Apply an effect map to a country.

        Effects whose key matches a ``CountryModel`` column (e.g.
        ``approval``, ``stability``, ``population``) are applied to that
        column directly. All other effects are treated as resource-key
        adjustments and routed through ``ResourceRepository.adjust`` so
        they actually persist (previously effects like ``food: -5000``
        were silently dropped because ``country.food`` doesn't exist).
        """
        for k, v in effects.items():
            try:
                amount = float(v)
            except (TypeError, ValueError):
                continue
            if k in _COUNTRY_ATTR_EFFECTS and hasattr(country, k):
                current = getattr(country, k) or 0.0
                # Population is stored as BigInt — keep it integral.
                if k == "population":
                    setattr(country, k, max(0, int(current + amount)))
                elif k == "housing_capacity":
                    setattr(country, k, max(0, int(current + amount)))
                else:
                    setattr(country, k, max(0.0, current + amount))
            else:
                # Treat as a resource stock adjustment (money, food,
                # water, wood, oil, etc.). ensure_stock creates the row
                # if missing so adjust() never fails on a fresh country.
                await self.resources.ensure_stock(country.id, country.world_id, k)
                await self.resources.adjust(country.id, k, amount)
        await self.session.flush()
