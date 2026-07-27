"""Military training service."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nationcraft.core.config import game_data
from nationcraft.core.events import Event, event_bus
from nationcraft.core.exceptions import GameRuleError, InsufficientResourcesError, NotFoundError
from nationcraft.infrastructure.db.models import CountryModel
from nationcraft.infrastructure.repositories import (
    ResourceRepository,
    UnitRepository,
)


class MilitaryService:
    """Training units, deployment, unit-state transitions."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.units = UnitRepository(session)
        self.resources = ResourceRepository(session)

    async def train(self, country_id: int, unit_key: str, count: int) -> int:
        udef = game_data.units.get(unit_key)
        if udef is None:
            raise NotFoundError(f"unknown unit: {unit_key}")

        # Check tech prerequisites.
        from nationcraft.infrastructure.db.models import ResearchNodeModel
        from nationcraft.domain.enums import ResearchStatus
        for tech in udef.requires_tech:
            stmt = select(ResearchNodeModel).where(
                ResearchNodeModel.country_id == country_id,
                ResearchNodeModel.key == tech,
                ResearchNodeModel.status == ResearchStatus.COMPLETED.value,
            )
            if (await self.session.execute(stmt)).scalar_one_or_none() is None:
                raise GameRuleError(f"missing required tech: {tech}")

        # Check building prerequisites (e.g., barracks for infantry).
        from nationcraft.domain.enums import BuildingStatus
        from nationcraft.infrastructure.db.models import BuildingModel
        for bk in udef.requires_building:
            stmt = select(BuildingModel).where(
                BuildingModel.country_id == country_id,
                BuildingModel.key == bk,
                BuildingModel.status == BuildingStatus.ACTIVE.value,
            )
            if (await self.session.execute(stmt)).scalar_one_or_none() is None:
                raise GameRuleError(f"missing required building: {bk}")

        # Pay cost.
        cost = {k: v * count for k, v in udef.cost.items()}
        if cost and not await self.resources.covers(country_id, cost):
            raise InsufficientResourcesError("insufficient resources for training")
        if cost:
            await self.resources.deduct(country_id, cost)

        unit = await self.units.adjust(country_id, unit_key, count)
        country = await self.session.get(CountryModel, country_id)
        await event_bus.publish(Event(
            type="unit.trained", world_id=country.world_id if country else None,
            payload={"country_id": country_id, "unit": unit_key, "count": count},
        ))
        return unit.count

    async def list_units(self, country_id: int) -> list[dict]:
        rows = await self.units.list_by_country(country_id)
        return [{"key": u.key, "count": u.count, "state": u.state.value} for u in rows]
