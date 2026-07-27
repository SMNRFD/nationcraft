"""Mission service: instantiate per-country, evaluate, claim."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nationcraft.core.config import game_data
from nationcraft.core.events import Event, event_bus
from nationcraft.core.exceptions import GameRuleError, NotFoundError
from nationcraft.domain.entities import Mission
from nationcraft.domain.enums import MissionCategory, MissionStatus
from nationcraft.infrastructure.db.models import CountryModel
from nationcraft.infrastructure.repositories import (
    MissionRepository,
    ResourceRepository,
)


class MissionService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = MissionRepository(session)
        self.resources = ResourceRepository(session)

    async def seed_for_country(self, country_id: int) -> None:
        """Seed tutorial + daily missions for a freshly-selected country."""
        country = await self.session.get(CountryModel, country_id)
        if country is None:
            return
        for mdef in game_data.missions.values():
            if mdef.category == MissionCategory.TUTORIAL.value or mdef.category == MissionCategory.DAILY.value:
                await self.repo.upsert(Mission(
                    id=0, world_id=country.world_id, country_id=country_id,
                    key=mdef.key, category=MissionCategory(mdef.category),
                    status=MissionStatus.ACTIVE,
                    expires_at=datetime.now(timezone.utc) + timedelta(seconds=mdef.expires_after_seconds or 86400),
                ))

    async def list_for_country(self, country_id: int) -> list[Mission]:
        return await self.repo.list_by_country(country_id)

    async def evaluate(self, country_id: int) -> int:
        """Walk all active missions for ``country_id`` and update progress."""
        missions = await self.repo.list_by_country(country_id)
        country = await self.session.get(CountryModel, country_id)
        if country is None:
            return 0
        completed = 0
        for m in missions:
            if m.status != MissionStatus.ACTIVE:
                continue
            mdef = game_data.missions.get(m.key)
            if not mdef:
                continue
            ctx = await self._build_context(country)
            obj = mdef.objective
            metric = obj.get("metric")
            target = obj.get("target")
            current = ctx.get(metric, 0)
            if current is None:
                continue
            m.progress = min(1.0, float(current) / float(target) if target else 0.0)
            if m.progress >= 1.0:
                m.status = MissionStatus.COMPLETED
                completed += 1
                await event_bus.publish(Event(
                    type="mission.completed", world_id=country.world_id,
                    payload={"country_id": country_id, "mission": m.key},
                ))
            await self.repo.upsert(m)
        return completed

    async def claim(self, country_id: int, mission_id: int) -> dict[str, float]:
        from nationcraft.infrastructure.db.models import MissionModel
        m = await self.session.get(MissionModel, mission_id)
        if m is None or m.country_id != country_id:
            raise NotFoundError("mission not found")
        if m.status != MissionStatus.COMPLETED.value:
            raise GameRuleError("mission not completed")
        mdef = game_data.missions.get(m.key)
        rewards = mdef.reward if mdef else {}
        # Apply rewards.
        for key, amount in rewards.items():
            await self.resources.adjust(country_id, key, amount)
        m.status = MissionStatus.CLAIMED.value
        m.claimed_at = datetime.now(timezone.utc)
        await self.session.flush()
        return rewards

    async def _build_context(self, country: CountryModel) -> dict:
        stocks = await self.resources.list_by_country(country.id)
        return {
            **{s.key: s.amount for s in stocks},
            "population": country.population,
            "treasury": country.treasury,
            "approval": country.approval,
            "stability": country.stability,
        }
