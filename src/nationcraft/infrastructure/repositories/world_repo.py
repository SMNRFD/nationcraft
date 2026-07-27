"""World repository."""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from nationcraft.domain.entities import World
from nationcraft.domain.enums import WorldStatus
from nationcraft.infrastructure.db.models import WorldModel


class WorldRepository:
    """SQLAlchemy implementation of :class:`IWorldRepository`."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, world_id: int) -> World | None:
        m = await self.session.get(WorldModel, world_id)
        return self._to_entity(m) if m else None

    async def get_by_slug(self, slug: str) -> World | None:
        stmt = select(WorldModel).where(WorldModel.slug == slug, WorldModel.deleted_at.is_(None))
        m = (await self.session.execute(stmt)).scalar_one_or_none()
        return self._to_entity(m) if m else None

    async def list_open(self) -> list[World]:
        stmt = select(WorldModel).where(
            WorldModel.status == WorldStatus.OPEN.value, WorldModel.deleted_at.is_(None)
        ).order_by(WorldModel.id)
        rows = (await self.session.execute(stmt)).scalars().all()
        return [self._to_entity(m) for m in rows]

    async def list_all(self) -> list[World]:
        stmt = select(WorldModel).where(WorldModel.deleted_at.is_(None)).order_by(WorldModel.id)
        rows = (await self.session.execute(stmt)).scalars().all()
        return [self._to_entity(m) for m in rows]

    async def list_active(self) -> list[World]:
        stmt = select(WorldModel).where(
            WorldModel.status.in_([WorldStatus.OPEN.value, WorldStatus.FULL.value]),
            WorldModel.deleted_at.is_(None),
        ).order_by(WorldModel.id)
        rows = (await self.session.execute(stmt)).scalars().all()
        return [self._to_entity(m) for m in rows]

    async def create(self, **kwargs: object) -> World:
        m = WorldModel(**kwargs)  # type: ignore[arg-type]
        self.session.add(m)
        await self.session.flush()
        return self._to_entity(m)

    async def update(self, world: World) -> World:
        stmt = (
            update(WorldModel)
            .where(WorldModel.id == world.id)
            .values(
                status=world.status.value if hasattr(world.status, "value") else world.status,
                player_count=world.player_count,
                tick_count=world.tick_count,
                last_tick_at=datetime.now(timezone.utc),
                meta=world.meta,
            )
            .returning(WorldModel)
        )
        m = (await self.session.execute(stmt)).scalar_one()
        return self._to_entity(m)

    async def increment_player_count(self, world_id: int, delta: int = 1) -> int:
        stmt = (
            update(WorldModel)
            .where(WorldModel.id == world_id)
            .values(player_count=WorldModel.player_count + delta)
        )
        await self.session.execute(stmt)
        m = await self.session.get(WorldModel, world_id)
        return m.player_count if m else 0

    async def increment_ticks(self, world_ids: list[int]) -> None:
        if not world_ids:
            return
        stmt = (
            update(WorldModel)
            .where(WorldModel.id.in_(world_ids))
            .values(
                tick_count=WorldModel.tick_count + 1,
                last_tick_at=datetime.now(timezone.utc),
            )
        )
        await self.session.execute(stmt)

    async def delete(self, world_id: int) -> bool:
        stmt = (
            update(WorldModel)
            .where(WorldModel.id == world_id)
            .values(deleted_at=datetime.now(timezone.utc), status=WorldStatus.ARCHIVED.value)
        )
        await self.session.execute(stmt)
        return True

    @staticmethod
    def _to_entity(m: WorldModel) -> World:
        return World(
            id=m.id,
            name=m.name,
            slug=m.slug,
            status=WorldStatus(m.status),
            player_capacity=m.player_capacity,
            player_count=m.player_count,
            tick_count=m.tick_count,
            created_at=m.created_at,
            meta=m.meta or {},
        )
