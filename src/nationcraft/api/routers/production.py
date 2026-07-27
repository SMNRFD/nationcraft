"""Production & research endpoints."""
from __future__ import annotations

from fastapi import APIRouter

from nationcraft.api.dependencies import CurrentPlayer, SessionDep
from nationcraft.api.schemas.envelope import success
from nationcraft.application.dto.game import BuildRequest, ResearchRequest, UpgradeRequest
from nationcraft.application.services import ProductionService, ResearchService
from nationcraft.infrastructure.db.models import PlayerModel

router = APIRouter(prefix="/production", tags=["production"])


async def _resolve_country(session, player_id: int) -> int:  # type: ignore[no-untyped-def]
    p = await session.get(PlayerModel, player_id)
    if not p or not p.country_id:
        from nationcraft.core.exceptions import GameRuleError
        raise GameRuleError("player has no country")
    return p.country_id


@router.get("/buildings", response_model=None)
async def list_buildings(session: SessionDep, player_id: CurrentPlayer) -> dict:
    cid = await _resolve_country(session, player_id)
    svc = ProductionService(session)
    rows = await svc.buildings.list_by_country(cid)
    return success([{
        "id": b.id, "key": b.key, "level": b.level, "status": b.status.value,
        "completes_at": b.completes_at.isoformat() if b.completes_at else None,
    } for b in rows])


@router.post("/build", response_model=None)
async def build(req: BuildRequest, session: SessionDep, player_id: CurrentPlayer) -> dict:
    cid = await _resolve_country(session, player_id)
    svc = ProductionService(session)
    ids = await svc.start_construction(cid, req.building_key, req.count)
    return success({"building_ids": ids})


@router.post("/upgrade", response_model=None)
async def upgrade(req: UpgradeRequest, session: SessionDep, player_id: CurrentPlayer) -> dict:
    cid = await _resolve_country(session, player_id)
    svc = ProductionService(session)
    level = await svc.upgrade_building(cid, req.building_id)
    return success({"building_id": req.building_id, "new_level": level})


@router.post("/research", response_model=None)
async def research(req: ResearchRequest, session: SessionDep, player_id: CurrentPlayer) -> dict:
    cid = await _resolve_country(session, player_id)
    svc = ResearchService(session)
    node = await svc.queue(cid, req.tech_key)
    return success({"tech": node.key, "status": node.status.value})
