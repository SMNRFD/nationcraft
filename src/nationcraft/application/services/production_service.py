"""Production & construction service.

Computes per-tick production/consumption from active buildings, applies
hook overrides for the formula, and handles construction completion.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nationcraft.core.config import game_data
from nationcraft.core.events import Event, event_bus
from nationcraft.core.exceptions import GameRuleError, InsufficientResourcesError, NotFoundError
from nationcraft.core.extensions import HookRegistry
from nationcraft.domain.enums import BuildingStatus
from nationcraft.infrastructure.db.models import BuildingModel, CountryModel
from nationcraft.infrastructure.repositories import (
    BuildingRepository,
    ResourceRepository,
)


class ProductionService:
    """Per-tick production engine and building lifecycle."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.buildings = BuildingRepository(session)
        self.resources = ResourceRepository(session)

    # ---------- construction ----------

    async def start_construction(
        self, country_id: int, building_key: str, count: int = 1
    ) -> list[int]:
        bdef = game_data.buildings.get(building_key)
        if bdef is None:
            raise NotFoundError(f"unknown building: {building_key}")

        country = await self.session.get(CountryModel, country_id)
        if country is None:
            raise NotFoundError("country not found")

        # Check tech/building prerequisites.
        for req in bdef.requires_tech:
            if not await self._has_tech(country_id, req):
                raise GameRuleError(f"missing technology: {req}")
        for req in bdef.requires_building:
            if not await self._has_building(country_id, req):
                raise GameRuleError(f"missing required building: {req}")

        ids: list[int] = []
        now = datetime.now(timezone.utc)
        for _ in range(count):
            cost = self._compute_cost(bdef, level=1)
            if not await self.resources.covers(country_id, cost):
                raise InsufficientResourcesError(
                    f"insufficient resources: {cost}", code="insufficient_resources"
                )
            await self.resources.deduct(country_id, cost)
            build_time = self._compute_build_time(bdef, level=1)
            b = await self.buildings.create(
                world_id=country.world_id,
                country_id=country_id,
                key=building_key,
                level=1,
                status=BuildingStatus.UNDER_CONSTRUCTION.value,
                started_at=now,
                completes_at=now + timedelta(seconds=build_time),
            )
            ids.append(b.id)
        return ids

    async def upgrade_building(self, country_id: int, building_id: int) -> int:
        b = await self.session.get(BuildingModel, building_id)
        if b is None or b.country_id != country_id:
            raise NotFoundError("building not found")
        if b.status != BuildingStatus.ACTIVE.value:
            raise GameRuleError("building not active")
        bdef = game_data.buildings[b.key]
        new_level = b.level + 1
        if new_level > bdef.max_level:
            raise GameRuleError("max level reached")
        cost = self._compute_cost(bdef, level=new_level)
        if not await self.resources.covers(country_id, cost):
            raise InsufficientResourcesError("insufficient resources")
        await self.resources.deduct(country_id, cost)
        b.level = new_level
        b.status = BuildingStatus.UNDER_CONSTRUCTION.value
        b.started_at = datetime.now(timezone.utc)
        b.completes_at = b.started_at + timedelta(seconds=self._compute_build_time(bdef, new_level))
        await self.session.flush()
        return new_level

    async def complete_constructions(self, now: datetime | None = None) -> int:
        """Mark all completed buildings as active. Returns count."""
        now = now or datetime.now(timezone.utc)
        stmt = select(BuildingModel).where(
            BuildingModel.status == BuildingStatus.UNDER_CONSTRUCTION.value,
            BuildingModel.completes_at <= now,
        )
        rows = (await self.session.execute(stmt)).scalars().all()
        for b in rows:
            b.status = BuildingStatus.ACTIVE.value
            await event_bus.publish(Event(
                type="factory.built",
                world_id=b.world_id,
                payload={"building_id": b.id, "key": b.key, "level": b.level},
            ))
        await self.session.flush()
        return len(rows)

    # ---------- production tick ----------

    async def process_production_tick(self, world_id: int, delta_seconds: int) -> dict[int, dict[str, float]]:
        """Compute and apply production/consumption for every active building.

        Returns a dict mapping ``country_id`` → applied net deltas.
        """
        stmt = (
            select(BuildingModel, CountryModel)
            .join(CountryModel, CountryModel.id == BuildingModel.country_id)
            .where(
                BuildingModel.world_id == world_id,
                BuildingModel.status == BuildingStatus.ACTIVE.value,
                CountryModel.world_id == world_id,
            )
        )
        rows = (await self.session.execute(stmt)).all()
        net_by_country: dict[int, dict[str, float]] = {}
        for b, country in rows:
            bdef = game_data.buildings.get(b.key)
            if bdef is None:
                continue
            scale = b.level * (delta_seconds / 60.0)  # base rates are per-minute
            prod = {k: v * scale for k, v in bdef.production.items()}
            cons = {k: v * scale for k, v in bdef.consumption.items()}
            # Allow extension hooks to override.
            prod = await HookRegistry.instance().invoke(
                "production.output", prod, building=b, level=b.level, delta=delta_seconds
            )
            # Ensure all stocks exist.
            for k in list(prod.keys()) + list(cons.keys()):
                await self.resources.ensure_stock(country.id, world_id, k)
            # First consume, then produce.
            net = {k: -v for k, v in cons.items()}
            for k, v in prod.items():
                net[k] = net.get(k, 0.0) + v
            if net:
                await self.resources.bulk_adjust(country.id, net)
                net_by_country.setdefault(country.id, {})
                for k, v in net.items():
                    net_by_country[country.id][k] = net_by_country[country.id].get(k, 0.0) + v
        await event_bus.publish(Event(
            type="production.tick", world_id=world_id,
            payload={"countries": len(net_by_country)},
        ))
        return net_by_country

    # ---------- helpers ----------

    def _compute_cost(self, bdef, level: int) -> dict[str, float]:  # type: ignore[no-untyped-def]
        return {k: v * (bdef.cost_growth ** (level - 1)) for k, v in bdef.base_cost.items()}

    def _compute_build_time(self, bdef, level: int) -> float:  # type: ignore[no-untyped-def]
        return bdef.base_build_time * (bdef.cost_growth ** (level - 1))

    async def _has_tech(self, country_id: int, tech_key: str) -> bool:
        from nationcraft.infrastructure.db.models import ResearchNodeModel
        from nationcraft.domain.enums import ResearchStatus
        stmt = select(ResearchNodeModel).where(
            ResearchNodeModel.country_id == country_id,
            ResearchNodeModel.key == tech_key,
            ResearchNodeModel.status == ResearchStatus.COMPLETED.value,
        )
        return (await self.session.execute(stmt)).scalar_one_or_none() is not None

    async def _has_building(self, country_id: int, key: str) -> bool:
        stmt = select(BuildingModel).where(
            BuildingModel.country_id == country_id,
            BuildingModel.key == key,
            BuildingModel.status == BuildingStatus.ACTIVE.value,
        )
        return (await self.session.execute(stmt)).scalar_one_or_none() is not None
