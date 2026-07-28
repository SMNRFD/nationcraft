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
        ctx = await self._build_context(country)
        for m in missions:
            if m.status != MissionStatus.ACTIVE:
                continue
            mdef = game_data.missions.get(m.key)
            if not mdef:
                continue
            obj = mdef.objective
            metric = obj.get("metric")
            target = obj.get("target", 0)
            op = obj.get("op", ">=")
            current = ctx.get(metric, 0)
            if current is None:
                continue
            try:
                current_f = float(current)
                target_f = float(target)
            except (TypeError, ValueError):
                continue
            # Compute progress as a 0..1 ratio, but honor the operator
            # for the "is complete?" check. Previously a mission with
            # ``op: ">"`` and ``target: 0`` (e.g. tut_select_country)
            # would never advance because ``current / 0`` was guarded by
            # ``if target`` (0 is falsy) and fell back to progress=0.0.
            if target_f > 0:
                progress = max(0.0, min(1.0, current_f / target_f))
            elif current_f > 0:
                # target=0 with a positive current → already complete.
                progress = 1.0
            else:
                progress = 0.0
            # Override progress to 1.0 if the operator says we're done.
            done = (
                (op == ">" and current_f > target_f)
                or (op == ">=" and current_f >= target_f)
                or (op == "<" and current_f < target_f)
                or (op == "<=" and current_f <= target_f)
                or (op == "==" and current_f == target_f)
            )
            if done:
                progress = 1.0
            m.progress = progress
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
        """Build a context dict mapping metric names to current values.

        Includes:
        - Every resource stock for the country (money, food, water, …).
        - Country-level numeric columns (population, treasury, approval, …).
        - Aggregate unit counts: ``soldiers`` = sum of all land-category
          units; per-unit-key counts (e.g. ``infantry``, ``tank``).

        The ``soldiers`` aggregate is what the tutorial mission
        ``tut_train_infantry`` checks (``metric: soldiers, target: 10``).
        Without it the mission could never complete even after the player
        trained 100 infantry, because the unit count lives in the
        ``units`` table — not in ``resource_stocks``.

        Note: ``research_points`` is treated as a resource stock (the
        production tick writes it there). The ``CountryModel`` also has
        a ``research_points`` column, but it's a legacy/dead field that
        is never updated — so we deliberately DON'T overwrite the
        resource stock value with the column value.
        """
        stocks = await self.resources.list_by_country(country.id)
        ctx: dict[str, float | int] = {
            **{s.key: s.amount for s in stocks},
            "population": country.population,
            "treasury": country.treasury,
            "approval": country.approval,
            "stability": country.stability,
            "corruption": country.corruption,
            "education": country.education,
            "healthcare": country.healthcare,
            # NB: do NOT add ``research_points`` from country.research_points
            # — that column is never updated by the production tick, so
            # overwriting the resource-stock value with it would make
            # every ``metric: research_points`` mission perpetually 0%.
        }
        # Aggregate unit counts so missions like ``tut_train_infantry``
        # (metric: soldiers) can see real progress.
        try:
            from nationcraft.infrastructure.repositories import UnitRepository
            unit_repo = UnitRepository(self.session)
            units = await unit_repo.list_by_country(country.id)
            soldiers_total = 0
            for u in units:
                ctx[u.key] = ctx.get(u.key, 0) + u.count
                # ``soldiers`` aggregates ALL unit categories (infantry,
                # tanks, special forces, etc.) — that matches what
                # players intuitively expect from the metric name.
                soldiers_total += u.count
            ctx["soldiers"] = soldiers_total
        except Exception:  # noqa: BLE001
            # Defensive: never break the tick engine because of a unit
            # lookup failure.
            pass
        return ctx
