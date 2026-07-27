"""Game events: trigger configurable random/scheduled events."""
from __future__ import annotations

import random
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nationcraft.core.config import game_data
from nationcraft.core.events import Event, event_bus
from nationcraft.infrastructure.db.models import CountryModel, GameEventModel
from nationcraft.infrastructure.repositories import GameEventRepository


class GameEventService:
    """Per-tick event triggering (weighted random sampling)."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = GameEventRepository(session)

    async def maybe_trigger(self, world_id: int, tick: int) -> int:
        """Roll for random events. Returns the number triggered."""
        eligible = [
            ev for ev in game_data.events.values()
            if ev.category == "random" and tick >= ev.min_world_age_ticks
        ]
        if not eligible:
            return 0
        count = 0
        for ev in eligible:
            # 1% base chance per tick.
            if random.random() < 0.01 * ev.weight:
                # Apply effects to a random country in the world.
                country = await self.session.scalar(
                    select(CountryModel).where(CountryModel.world_id == world_id).order_by("random()").limit(1)
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
        """Apply simple effect map to a country. Extensions can override via hook."""
        for k, v in effects.items():
            if hasattr(country, k):
                setattr(country, k, max(0.0, getattr(country, k) + float(v)))
