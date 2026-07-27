"""War & combat service with hookable formulas.

Combat is intentionally a *simple* but extensible model. A battle is
resolved by comparing attacker aggregate attack power vs. defender
aggregate defense power (both modified by tech, morale, terrain and
random variance), then applying proportional losses.

Extensions may override the calculation entirely by registering a
handler on the ``combat.resolve`` hook.
"""
from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from nationcraft.core.config import game_data
from nationcraft.core.events import Event, event_bus
from nationcraft.core.exceptions import GameRuleError, NotFoundError
from nationcraft.core.extensions import HookRegistry
from nationcraft.domain.entities import War
from nationcraft.domain.enums import WarStatus
from nationcraft.infrastructure.db.models import CountryModel, WarModel
from nationcraft.infrastructure.repositories import (
    UnitRepository,
    WarRepository,
)


@dataclass(slots=True)
class BattleResult:
    attacker_power: float
    defender_power: float
    attacker_losses: dict[str, int]
    defender_losses: dict[str, int]
    winner: str  # "attacker" | "defender" | "draw"
    war_score_delta: float


class WarService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = WarRepository(session)
        self.units = UnitRepository(session)

    async def declare_war(
        self, attacker_id: int, defender_id: int, war_type: str = "conventional"
    ) -> War:
        attacker = await self.session.get(CountryModel, attacker_id)
        defender = await self.session.get(CountryModel, defender_id)
        if not attacker or not defender:
            raise NotFoundError("country not found")
        if attacker.world_id != defender.world_id:
            raise GameRuleError("cannot attack across worlds")

        # Existing active war?
        active = await self.repo.list_active_for_country(attacker_id)
        if any(
            (w.attacker_id == defender_id or w.defender_id == defender_id)
            and w.status in (WarStatus.DECLARED, WarStatus.ACTIVE)
            for w in active
        ):
            raise GameRuleError("already at war with this country")

        war = await self.repo.create(
            world_id=attacker.world_id,
            attacker_id=attacker_id,
            defender_id=defender_id,
            status=WarStatus.DECLARED.value,
            war_type=war_type,
            declared_at=datetime.now(timezone.utc),
        )
        await event_bus.publish(Event(
            type="war.declared", world_id=attacker.world_id,
            payload={"war_id": war.id, "attacker_id": attacker_id, "defender_id": defender_id,
                     "war_type": war_type},
        ))
        return war

    async def attack(
        self,
        war_id: int,
        attacker_units: dict[str, int],
        defender_units: dict[str, int] | None = None,
    ) -> BattleResult:
        war = await self.session.get(WarModel, war_id)
        if war is None:
            raise NotFoundError("war not found")
        if war.status not in (WarStatus.DECLARED.value, WarStatus.ACTIVE.value):
            raise GameRuleError("war not active")

        # Resolve battle with hook override.
        result: BattleResult = await HookRegistry.instance().invoke(
            "combat.resolve",
            self._default_resolve(attacker_units, defender_units or {}),
            attacker_units=attacker_units,
            defender_units=defender_units or {},
        )

        # Apply unit losses.
        for k, n in result.attacker_losses.items():
            await self.units.adjust(war.attacker_id, k, -n)
        for k, n in result.defender_losses.items():
            await self.units.adjust(war.defender_id, k, -n)

        # Update war score.
        war.status = WarStatus.ACTIVE.value
        if result.winner == "attacker":
            war.attacker_war_score += result.war_score_delta
        elif result.winner == "defender":
            war.defender_war_score += result.war_score_delta

        await self.repo.record_battle(
            war_id=war_id, attacker_id=war.attacker_id, defender_id=war.defender_id,
            attacker_loss=result.attacker_losses, defender_loss=result.defender_losses,
            winner_id=war.attacker_id if result.winner == "attacker"
            else (war.defender_id if result.winner == "defender" else None),
        )

        await event_bus.publish(Event(
            type="attack.finished", world_id=war.world_id,
            payload={"war_id": war_id, "winner": result.winner,
                     "war_score_delta": result.war_score_delta},
        ))
        return result

    async def end_war(self, war_id: int, *, winner_id: int | None = None) -> War:
        m = await self.session.get(WarModel, war_id)
        if m is None:
            raise NotFoundError("war not found")
        m.status = WarStatus.ENDED.value
        m.ended_at = datetime.now(timezone.utc)
        m.winner_id = winner_id
        await self.session.flush()
        return self.repo._to_entity(m)  # type: ignore[attr-defined]

    def _default_resolve(
        self, attacker_units: dict[str, int], defender_units: dict[str, int]
    ) -> BattleResult:
        a_power = sum(game_data.units[k].attack * n for k, n in attacker_units.items() if k in game_data.units)
        d_power = sum(game_data.units[k].defense * n for k, n in defender_units.items() if k in game_data.units)
        a_power *= random.uniform(0.85, 1.15)  # variance
        d_power *= random.uniform(0.85, 1.15)

        if a_power > d_power:
            winner = "attacker"
            delta = (a_power - d_power) / max(a_power, 1.0) * 25.0
            a_loss_pct = 0.05
            d_loss_pct = 0.20
        elif d_power > a_power:
            winner = "defender"
            delta = (d_power - a_power) / max(d_power, 1.0) * 25.0
            a_loss_pct = 0.25
            d_loss_pct = 0.05
        else:
            winner = "draw"
            delta = 0.0
            a_loss_pct = d_loss_pct = 0.10

        a_losses = {k: int(n * a_loss_pct) for k, n in attacker_units.items()}
        d_losses = {k: int(n * d_loss_pct) for k, n in defender_units.items()}
        return BattleResult(
            attacker_power=round(a_power, 2),
            defender_power=round(d_power, 2),
            attacker_losses=a_losses,
            defender_losses=d_losses,
            winner=winner,
            war_score_delta=round(delta, 2),
        )
