"""Integration test for the war service."""
from __future__ import annotations

import pytest

from nationcraft.application.services import WarService
from nationcraft.core.exceptions import GameRuleError
from nationcraft.infrastructure.db.models import CountryModel
from nationcraft.infrastructure.repositories import ResourceRepository, UnitRepository


@pytest.mark.asyncio
async def test_declare_war_and_attack(session) -> None:
    # Two countries in same world.
    attacker = CountryModel(world_id=1, code="AT", name="Attacker", population=100, treasury=0)
    defender = CountryModel(world_id=1, code="DF", name="Defender", population=100, treasury=0)
    session.add_all([attacker, defender])
    await session.flush()

    # Give both sides some units.
    units_repo = UnitRepository(session)
    await units_repo.adjust(attacker.id, "infantry", 100)
    await units_repo.adjust(defender.id, "infantry", 50)
    await session.commit()

    svc = WarService(session)
    war = await svc.declare_war(attacker.id, defender.id, "conventional")
    assert war.attacker_id == attacker.id
    assert war.defender_id == defender.id
    await session.commit()

    # Cannot declare twice.
    with pytest.raises(GameRuleError):
        await svc.declare_war(attacker.id, defender.id)
    await session.rollback()

    # Run an attack.
    result = await svc.attack(war.id, attacker_units={"infantry": 100}, defender_units={"infantry": 50})
    assert result.winner in ("attacker", "defender", "draw")
    assert result.attacker_power > 0
    assert result.defender_power > 0
    # Some units should be lost.
    assert sum(result.attacker_losses.values()) + sum(result.defender_losses.values()) > 0
    await session.commit()
