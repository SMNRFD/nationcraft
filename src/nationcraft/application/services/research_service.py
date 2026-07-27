"""Research service: queue research, advance per tick, complete."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from nationcraft.core.config import game_data
from nationcraft.core.events import Event, event_bus
from nationcraft.core.exceptions import GameRuleError, InsufficientResourcesError, NotFoundError
from nationcraft.domain.entities import ResearchNode
from nationcraft.domain.enums import ResearchStatus
from nationcraft.infrastructure.db.models import CountryModel, ResearchNodeModel
from nationcraft.infrastructure.repositories import ResearchRepository, ResourceRepository


class ResearchService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = ResearchRepository(session)
        self.resources = ResourceRepository(session)

    async def queue(self, country_id: int, tech_key: str) -> ResearchNode:
        tdef = game_data.techs.get(tech_key)
        if tdef is None:
            raise NotFoundError(f"unknown tech: {tech_key}")
        existing = await self.repo.get(country_id, tech_key)
        if existing and existing.status in (ResearchStatus.COMPLETED, ResearchStatus.IN_PROGRESS):
            raise GameRuleError(f"tech {tech_key} already {existing.status.value}")

        # Check prerequisites.
        for req in tdef.requires:
            prereq = await self.repo.get(country_id, req)
            if prereq is None or prereq.status != ResearchStatus.COMPLETED:
                raise GameRuleError(f"missing prerequisite: {req}")

        country = await self.session.get(CountryModel, country_id)
        if country is None:
            raise NotFoundError("country not found")

        # Pay research cost.
        if tdef.research_cost:
            if not await self.resources.covers(country_id, tdef.research_cost):
                raise InsufficientResourcesError("insufficient resources for research")
            await self.resources.deduct(country_id, tdef.research_cost)

        now = datetime.now(timezone.utc)
        node = ResearchNode(
            id=0,
            world_id=country.world_id,
            country_id=country_id,
            key=tech_key,
            status=ResearchStatus.IN_PROGRESS,
            started_at=now,
            completes_at=now + timedelta(seconds=tdef.research_time),
        )
        node = await self.repo.upsert(node)
        await event_bus.publish(Event(
            type="research.queued", world_id=country.world_id,
            payload={"country_id": country_id, "tech": tech_key},
        ))
        return node

    async def advance_research_tick(self, world_id: int, delta_seconds: int) -> int:
        """Complete any research whose completes_at has passed. Returns count."""
        now = datetime.now(timezone.utc)
        stmt = select(ResearchNodeModel).where(
            ResearchNodeModel.world_id == world_id,
            ResearchNodeModel.status == ResearchStatus.IN_PROGRESS.value,
            ResearchNodeModel.completes_at <= now,
        )
        rows = (await self.session.execute(stmt)).scalars().all()
        for r in rows:
            r.status = ResearchStatus.COMPLETED.value
            r.progress = 1.0
            tdef = game_data.techs.get(r.key)
            await event_bus.publish(Event(
                type="research.completed", world_id=world_id,
                payload={"country_id": r.country_id, "tech": r.key,
                         "effects": tdef.effects if tdef else {}},
            ))
        await self.session.flush()
        return len(rows)
