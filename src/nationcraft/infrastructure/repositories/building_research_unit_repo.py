"""Buildings, research, units repositories."""
from __future__ import annotations

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from nationcraft.domain.entities import Building, ResearchNode, Unit
from nationcraft.domain.enums import BuildingStatus, ResearchStatus, UnitState
from nationcraft.infrastructure.db.models import (
    BuildingModel,
    CountryModel,
    ResearchNodeModel,
    UnitModel,
)


class BuildingRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_by_country(self, country_id: int) -> list[Building]:
        stmt = select(BuildingModel).where(BuildingModel.country_id == country_id)
        rows = (await self.session.execute(stmt)).scalars().all()
        return [self._to_entity(m) for m in rows]

    async def list_completing_before(self, when) -> list[Building]:
        stmt = select(BuildingModel).where(
            BuildingModel.status == BuildingStatus.UNDER_CONSTRUCTION.value,
            BuildingModel.completes_at <= when,
        )
        rows = (await self.session.execute(stmt)).scalars().all()
        return [self._to_entity(m) for m in rows]

    async def create(self, **kwargs: object) -> Building:
        m = BuildingModel(**kwargs)  # type: ignore[arg-type]
        self.session.add(m)
        await self.session.flush()
        return self._to_entity(m)

    async def update(self, building: Building) -> Building:
        stmt = (
            update(BuildingModel)
            .where(BuildingModel.id == building.id)
            .values(
                level=building.level,
                status=building.status.value,
                started_at=building.started_at,
                completes_at=building.completes_at,
                produced_total=building.produced_total,
            )
            .returning(BuildingModel)
        )
        m = (await self.session.execute(stmt)).scalar_one()
        return self._to_entity(m)

    async def delete(self, building_id: int) -> bool:
        m = await self.session.get(BuildingModel, building_id)
        if m:
            await self.session.delete(m)
            return True
        return False

    @staticmethod
    def _to_entity(m: BuildingModel) -> Building:
        return Building(
            id=m.id,
            world_id=m.world_id,
            country_id=m.country_id,
            key=m.key,
            level=m.level,
            status=BuildingStatus(m.status),
            position_x=m.position_x,
            position_y=m.position_y,
            started_at=m.started_at,
            completes_at=m.completes_at,
            produced_total=m.produced_total,
        )


class ResearchRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_by_country(self, country_id: int) -> list[ResearchNode]:
        stmt = select(ResearchNodeModel).where(ResearchNodeModel.country_id == country_id)
        rows = (await self.session.execute(stmt)).scalars().all()
        return [self._to_entity(m) for m in rows]

    async def get(self, country_id: int, key: str) -> ResearchNode | None:
        stmt = select(ResearchNodeModel).where(
            ResearchNodeModel.country_id == country_id,
            ResearchNodeModel.key == key,
        )
        m = (await self.session.execute(stmt)).scalar_one_or_none()
        return self._to_entity(m) if m else None

    async def upsert(self, node: ResearchNode) -> ResearchNode:
        existing = await self.get(node.country_id, node.key)
        if existing is None:
            m = ResearchNodeModel(
                world_id=node.world_id,
                country_id=node.country_id,
                key=node.key,
                status=node.status.value,
                progress=node.progress,
                started_at=node.started_at,
                completes_at=node.completes_at,
            )
            self.session.add(m)
            await self.session.flush()
            return self._to_entity(m)
        stmt = (
            update(ResearchNodeModel)
            .where(ResearchNodeModel.id == existing.id)
            .values(
                status=node.status.value,
                progress=node.progress,
                started_at=node.started_at,
                completes_at=node.completes_at,
            )
            .returning(ResearchNodeModel)
        )
        m = (await self.session.execute(stmt)).scalar_one()
        return self._to_entity(m)

    @staticmethod
    def _to_entity(m: ResearchNodeModel) -> ResearchNode:
        return ResearchNode(
            id=m.id,
            world_id=m.world_id,
            country_id=m.country_id,
            key=m.key,
            status=ResearchStatus(m.status),
            started_at=m.started_at,
            completes_at=m.completes_at,
        )


class UnitRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_by_country(self, country_id: int) -> list[Unit]:
        stmt = select(UnitModel).where(UnitModel.country_id == country_id)
        rows = (await self.session.execute(stmt)).scalars().all()
        return [self._to_entity(m) for m in rows]

    async def get(self, country_id: int, key: str) -> Unit | None:
        stmt = select(UnitModel).where(
            UnitModel.country_id == country_id, UnitModel.key == key
        )
        m = (await self.session.execute(stmt)).scalar_one_or_none()
        return self._to_entity(m) if m else None

    async def adjust(self, country_id: int, key: str, delta: int) -> Unit:
        existing = await self.get(country_id, key)
        if existing is None:
            # Resolve the real world_id from the country so the FK
            # constraint (units.world_id -> worlds.id) is satisfied.
            # Previously this hardcoded world_id=0 which (a) breaks
            # referential integrity and (b) makes world-scoped unit
            # queries (used by rankings, war resolution, tick engine)
            # silently miss every newly-created unit row.
            country = await self.session.get(CountryModel, country_id)
            world_id = country.world_id if country else 0
            m = UnitModel(
                world_id=world_id,
                country_id=country_id,
                key=key,
                count=max(0, delta),
                state=UnitState.IDLE.value,
            )
            self.session.add(m)
            await self.session.flush()
            return self._to_entity(m)
        stmt = (
            update(UnitModel)
            .where(UnitModel.id == existing.id)
            .values(count=max(0, existing.count + delta))
            .returning(UnitModel)
        )
        m = (await self.session.execute(stmt)).scalar_one()
        return self._to_entity(m)

    async def create(self, **kwargs: object) -> Unit:
        m = UnitModel(**kwargs)  # type: ignore[arg-type]
        self.session.add(m)
        await self.session.flush()
        return self._to_entity(m)

    @staticmethod
    def _to_entity(m: UnitModel) -> Unit:
        return Unit(
            id=m.id,
            world_id=m.world_id,
            country_id=m.country_id,
            key=m.key,
            count=m.count,
            state=UnitState(m.state),
            region_id=m.region_id,
            deployed_at=m.deployed_at,
        )
