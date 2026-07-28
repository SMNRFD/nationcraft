"""Country service: selection, state queries, abandonment."""
from __future__ import annotations

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from nationcraft.application.dto.game import CountryDTO, ResourceStockDTO
from nationcraft.application.services.world_service import WorldService
from nationcraft.core.config import game_data
from nationcraft.core.events import Event, event_bus
from nationcraft.core.exceptions import ConflictError, GameRuleError, NotFoundError
from nationcraft.infrastructure.db.models import (
    CountryModel,
    PlayerModel,
    ResourceStockModel,
)
from nationcraft.infrastructure.repositories import (
    BuildingRepository,
    CountryRepository,
    ResourceRepository,
    UnitRepository,
)


class CountryService:
    """Selecting & abandoning countries, snapshotting country state."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = CountryRepository(session)
        self.resources = ResourceRepository(session)

    async def select_country(self, player_id: int, world_id: int, country_code: str) -> CountryDTO:
        country = await self.session.scalar(
            select(CountryModel).where(
                CountryModel.world_id == world_id,
                CountryModel.code == country_code.upper(),
                CountryModel.player_id.is_(None),
                CountryModel.deleted_at.is_(None),
            ).with_for_update()
        )
        if country is None:
            raise ConflictError("country not available", code="country_unavailable")

        # Assign player
        country.player_id = player_id
        await self.session.execute(
            update(PlayerModel)
            .where(PlayerModel.id == player_id)
            .values(world_id=world_id, country_id=country.id)
        )

        # Seed starting resources, buildings, etc.
        cdef = game_data.countries.get(country.code)
        if cdef:
            for key, amount in cdef.starting_resources.items():
                await self.resources.ensure_stock(country.id, world_id, key)
                await self.resources.set_amount(country.id, key, amount)
            # Seed starting buildings (mark as active immediately).
            from datetime import datetime, timezone
            from nationcraft.domain.enums import BuildingStatus, ResearchStatus
            from nationcraft.infrastructure.db.models import BuildingModel, ResearchNodeModel
            for bkey, count in cdef.starting_buildings.items():
                for _ in range(count):
                    self.session.add(BuildingModel(
                        world_id=world_id,
                        country_id=country.id,
                        key=bkey,
                        level=1,
                        status=BuildingStatus.ACTIVE.value,
                        started_at=datetime.now(timezone.utc),
                        completes_at=None,
                    ))
            # Seed starting technologies (mark as completed immediately).
            # Bug: this was missing — players who selected a country with
            # starting_technologies never got those techs, so they
            # couldn't build anything that required them.
            for tech_key in cdef.starting_technologies:
                # Don't re-create if already exists from a prior assignment.
                existing = await self.session.scalar(
                    select(ResearchNodeModel).where(
                        ResearchNodeModel.country_id == country.id,
                        ResearchNodeModel.key == tech_key,
                    )
                )
                if existing is None:
                    self.session.add(ResearchNodeModel(
                        world_id=world_id,
                        country_id=country.id,
                        key=tech_key,
                        status=ResearchStatus.COMPLETED.value,
                        progress=100.0,
                        started_at=datetime.now(timezone.utc),
                        completes_at=datetime.now(timezone.utc),
                    ))
            await self.session.flush()

        # Increase world player count (which may trigger auto-creation).
        ws = WorldService(self.session)
        await ws.increment_player_count(world_id, delta=1)

        await event_bus.publish(Event(
            type="country.selected",
            world_id=world_id,
            player_id=player_id,
            payload={"country_id": country.id, "code": country.code},
        ))
        return self._dto(country)

    async def abandon_country(self, player_id: int) -> None:
        # Use a fresh query to ensure we don't read stale cached state.
        from sqlalchemy import select
        player = await self.session.scalar(
            select(PlayerModel).where(PlayerModel.id == player_id)
        )
        if not player or not player.country_id:
            raise GameRuleError("player has no country")
        country = await self.session.get(CountryModel, player.country_id)
        if country is None:
            await self.session.execute(
                update(PlayerModel)
                .where(PlayerModel.id == player_id)
                .values(country_id=None, world_id=None)
            )
            return
        country.player_id = None
        await self.session.execute(
            update(PlayerModel)
            .where(PlayerModel.id == player_id)
            .values(country_id=None, world_id=None)
        )
        await self.session.flush()
        await event_bus.publish(Event(
            type="country.abandoned",
            player_id=player_id,
            payload={"country_id": country.id},
        ))

    async def get_country(self, country_id: int) -> CountryDTO:
        c = await self.repo.get(country_id)
        if c is None:
            raise NotFoundError("country not found")
        return self._dto_from_entity(c)

    async def list_by_world(self, world_id: int) -> list[CountryDTO]:
        rows = await self.repo.list_by_world(world_id)
        return [self._dto_from_entity(c) for c in rows]

    async def list_available(self, world_id: int) -> list[CountryDTO]:
        rows = await self.repo.list_available_in_world(world_id)
        return [self._dto_from_entity(c) for c in rows]

    async def snapshot(self, country_id: int) -> dict:
        """Returns the full snapshot used for the dashboard view."""
        country = await self.repo.get(country_id)
        if country is None:
            raise NotFoundError("country not found")
        resources = await self.resources.list_by_country(country_id)
        buildings = await BuildingRepository(self.session).list_by_country(country_id)
        units = await UnitRepository(self.session).list_by_country(country_id)
        return {
            "country": self._dto_from_entity(country).model_dump(),
            "resources": [ResourceStockDTO(key=r.key, amount=r.amount, capacity=r.capacity).model_dump() for r in resources],
            "buildings": [{"id": b.id, "key": b.key, "level": b.level, "status": b.status.value} for b in buildings],
            "units": [{"id": u.id, "key": u.key, "count": u.count, "state": u.state.value} for u in units],
        }

    @staticmethod
    def _dto(m: CountryModel) -> CountryDTO:
        return CountryDTO(
            id=m.id, world_id=m.world_id, player_id=m.player_id, code=m.code, name=m.name,
            flag_emoji=m.flag_emoji, government=m.government, population=m.population,
            treasury=m.treasury, approval=m.approval, stability=m.stability,
            corruption=m.corruption, education=m.education, healthcare=m.healthcare,
            electricity_balance=m.electricity_balance,
        )

    @staticmethod
    def _dto_from_entity(c) -> CountryDTO:  # type: ignore[no-untyped-def]
        return CountryDTO(
            id=c.id, world_id=c.world_id, player_id=c.player_id, code=c.code, name=c.name,
            flag_emoji=c.flag_emoji, government=c.government.value, population=c.population,
            treasury=c.treasury, approval=c.approval, stability=c.stability,
            corruption=c.corruption, education=c.education, healthcare=c.healthcare,
            electricity_balance=c.electricity_balance,
        )
