"""Military & war endpoints."""
from __future__ import annotations

from fastapi import APIRouter

from nationcraft.api.dependencies import CurrentPlayer, SessionDep
from nationcraft.api.schemas.envelope import success
from nationcraft.application.dto.game import AttackRequest, DeclareWarRequest, TrainRequest
from nationcraft.application.services import MilitaryService, WarService
from nationcraft.infrastructure.db.models import PlayerModel

router = APIRouter(prefix="/military", tags=["military"])


async def _resolve_country(session, player_id: int) -> int:  # type: ignore[no-untyped-def]
    p = await session.get(PlayerModel, player_id)
    if not p or not p.country_id:
        from nationcraft.core.exceptions import GameRuleError
        raise GameRuleError("player has no country")
    return p.country_id


@router.get("/units", response_model=None)
async def list_units(session: SessionDep, player_id: CurrentPlayer) -> dict:
    cid = await _resolve_country(session, player_id)
    svc = MilitaryService(session)
    units = await svc.list_units(cid)
    return success(units)


@router.post("/train", response_model=None)
async def train(req: TrainRequest, session: SessionDep, player_id: CurrentPlayer) -> dict:
    cid = await _resolve_country(session, player_id)
    svc = MilitaryService(session)
    count = await svc.train(cid, req.unit_key, req.count)
    return success({"unit_key": req.unit_key, "total": count})


@router.post("/war/declare", response_model=None)
async def declare_war(
    req: DeclareWarRequest, session: SessionDep, player_id: CurrentPlayer
) -> dict:
    cid = await _resolve_country(session, player_id)
    svc = WarService(session)
    war = await svc.declare_war(cid, req.defender_id, req.war_type)
    return success({"war_id": war.id, "status": war.status.value})


@router.post("/war/attack", response_model=None)
async def attack(req: AttackRequest, session: SessionDep, player_id: CurrentPlayer) -> dict:
    svc = WarService(session)
    result = await svc.attack(req.war_id, req.attacker_units, req.defender_units)
    return success({
        "attacker_power": result.attacker_power,
        "defender_power": result.defender_power,
        "attacker_losses": result.attacker_losses,
        "defender_losses": result.defender_losses,
        "winner": result.winner,
        "war_score_delta": result.war_score_delta,
    })


@router.get("/wars", response_model=None)
async def list_wars(session: SessionDep, player_id: CurrentPlayer) -> dict:
    cid = await _resolve_country(session, player_id)
    svc = WarService(session)
    wars = await svc.repo.list_active_for_country(cid)
    return success([{
        "id": w.id, "attacker_id": w.attacker_id, "defender_id": w.defender_id,
        "status": w.status.value, "war_type": w.war_type,
        "attacker_war_score": w.attacker_war_score,
        "defender_war_score": w.defender_war_score,
    } for w in wars])
