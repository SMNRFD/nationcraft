"""World service: creation, capacity management, auto-balancing."""
from __future__ import annotations

import re

from sqlalchemy import select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from nationcraft.application.dto.game import WorldDTO
from nationcraft.core.config import game_data, settings
from nationcraft.core.events import Event, event_bus
from nationcraft.core.exceptions import ConflictError, NotFoundError
from nationcraft.domain.enums import WorldStatus
from nationcraft.infrastructure.db.models import CountryModel, WorldModel


def _slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "world"


class WorldService:
    """Manages worlds, player capacity, and auto-creation."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def ensure_worlds(self, capacity: int | None = None) -> list[WorldDTO]:
        """Ensure at least one open world exists; auto-create as needed."""
        capacity = capacity or settings.WORLD_PLAYER_CAPACITY
        existing = await self.list_open()
        if not existing:
            await self.create_world(name="World 1", capacity=capacity)
            existing = await self.list_open()
        return existing

    async def create_world(self, *, name: str, capacity: int | None = None) -> WorldDTO:
        capacity = capacity or settings.WORLD_PLAYER_CAPACITY
        slug = _slugify(name)
        if await self.get_by_slug(slug):
            raise ConflictError(f"world with slug {slug} already exists", code="world_exists")
        world = WorldModel(
            name=name,
            slug=slug,
            status=WorldStatus.OPEN.value,
            player_capacity=capacity,
        )
        self.session.add(world)
        await self.session.flush()
        # Seed countries from game data.
        await self._seed_countries(world.id)
        await event_bus.publish(Event(
            type="world.created",
            world_id=world.id,
            payload={"name": world.name, "capacity": world.player_capacity},
        ))
        return self._dto(world)

    async def get(self, world_id: int) -> WorldDTO:
        m = await self.session.get(WorldModel, world_id)
        if not m:
            raise NotFoundError("world not found")
        return self._dto(m)

    async def get_by_slug(self, slug: str) -> WorldDTO | None:
        m = await self.session.scalar(
            select(WorldModel).where(WorldModel.slug == slug, WorldModel.deleted_at.is_(None))
        )
        return self._dto(m) if m else None

    async def list_open(self) -> list[WorldDTO]:
        rows = await self.session.scalars(
            select(WorldModel).where(
                WorldModel.status == WorldStatus.OPEN.value,
                WorldModel.deleted_at.is_(None),
            ).order_by(WorldModel.id)
        )
        return [self._dto(m) for m in rows]

    async def list_all_active(self) -> list[WorldDTO]:
        rows = await self.session.scalars(
            select(WorldModel).where(
                WorldModel.status.in_([WorldStatus.OPEN.value, WorldStatus.FULL.value]),
                WorldModel.deleted_at.is_(None),
            ).order_by(WorldModel.id)
        )
        return [self._dto(m) for m in rows]

    async def increment_player_count(self, world_id: int, delta: int = 1) -> None:
        world = await self.session.get(WorldModel, world_id)
        if world is None:
            raise NotFoundError("world not found")
        world.player_count = max(0, world.player_count + delta)
        if world.player_count >= world.player_capacity:
            world.status = WorldStatus.FULL.value
            await event_bus.publish(Event(
                type="world.filled", world_id=world.id, payload={"capacity": world.player_capacity}
            ))
            if settings.WORLD_AUTO_CREATE:
                next_name = f"World {world.id + 1}"
                await self.create_world(name=next_name, capacity=world.player_capacity)
        await self.session.flush()

    async def increment_ticks(self, world_ids: list[int]) -> None:
        if not world_ids:
            return
        await self.session.execute(
            update(WorldModel)
            .where(WorldModel.id.in_(world_ids))
            .values(
                tick_count=WorldModel.tick_count + 1,
                last_tick_at=text("now()"),
            )
        )

    async def _seed_countries(self, world_id: int) -> None:
        """Insert every country template into the new world."""
        for code, cdef in game_data.countries.items():
            self.session.add(CountryModel(
                world_id=world_id,
                code=code,
                name=cdef.name,
                flag_emoji=cdef.flag_emoji,
                population=cdef.starting_population,
                treasury=cdef.starting_treasury,
            ))
        await self.session.flush()

    @staticmethod
    def _dto(m: WorldModel) -> WorldDTO:
        return WorldDTO(
            id=m.id,
            name=m.name,
            slug=m.slug,
            status=m.status,
            player_capacity=m.player_capacity,
            player_count=m.player_count,
            tick_count=m.tick_count,
        )
