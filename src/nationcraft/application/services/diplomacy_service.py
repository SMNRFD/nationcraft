"""Diplomacy service."""
from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from nationcraft.core.events import Event, event_bus
from nationcraft.core.exceptions import GameRuleError, NotFoundError
from nationcraft.domain.entities import Diplomacy
from nationcraft.domain.enums import DiplomaticStatus
from nationcraft.infrastructure.db.models import CountryModel
from nationcraft.infrastructure.repositories import DiplomacyRepository


class DiplomacyService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = DiplomacyRepository(session)

    async def set_status(
        self, country_id: int, other_country_id: int, status: str
    ) -> Diplomacy:
        if country_id == other_country_id:
            raise GameRuleError("cannot set diplomacy with self")
        try:
            status_enum = DiplomaticStatus(status)
        except ValueError as e:
            raise GameRuleError(f"invalid diplomatic status: {status}") from e

        a = await self.session.get(CountryModel, country_id)
        b = await self.session.get(CountryModel, other_country_id)
        if a is None or b is None:
            raise NotFoundError("country not found")
        if a.world_id != b.world_id:
            raise GameRuleError("cannot set diplomacy across worlds")

        # Normalize ordering so the lower-id is country_a.
        if country_id > other_country_id:
            country_id, other_country_id = other_country_id, country_id

        diplo = Diplomacy(
            id=0, world_id=a.world_id,
            country_a_id=country_id, country_b_id=other_country_id,
            status=status_enum,
        )
        diplo = await self.repo.upsert(diplo)
        await event_bus.publish(Event(
            type="diplomacy.changed", world_id=a.world_id,
            payload={"a": country_id, "b": other_country_id, "status": status_enum.value},
        ))
        return diplo

    async def list_for_country(self, country_id: int) -> list[Diplomacy]:
        return await self.repo.list_for_country(country_id)
