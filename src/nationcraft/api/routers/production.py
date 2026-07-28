"""Production & research endpoints."""
from __future__ import annotations

from fastapi import APIRouter

from nationcraft.api.dependencies import CurrentPlayer, SessionDep
from nationcraft.api.schemas.envelope import success
from nationcraft.application.dto.game import BuildRequest, ResearchRequest, UpgradeRequest
from nationcraft.application.services import ProductionService, ResearchService
from nationcraft.core.config import game_data
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
    """List the player's existing buildings (active + under construction)."""
    cid = await _resolve_country(session, player_id)
    svc = ProductionService(session)
    rows = await svc.buildings.list_by_country(cid)
    return success([{
        "id": b.id, "key": b.key, "level": b.level, "status": b.status.value,
        "completes_at": b.completes_at.isoformat() if b.completes_at else None,
    } for b in rows])


@router.get("/buildings/catalog", response_model=None)
async def buildings_catalog(player_id: CurrentPlayer) -> dict:
    """Return the static catalog of all buildable buildings.

    Each entry includes the building's base cost, production, consumption,
    required tech, and required buildings. The client uses this to render
    the build menu without having to hard-code the catalog.
    """
    items = []
    for key, b in sorted(game_data.buildings.items()):
        items.append({
            "key": b.key,
            "name": b.name,
            "category": b.category,
            "description": b.description,
            "max_level": b.max_level,
            "base_cost": b.base_cost,
            "cost_growth": b.cost_growth,
            "base_build_time": b.base_build_time,
            "production": b.production,
            "consumption": b.consumption,
            "storage": b.storage,
            "requires_tech": b.requires_tech,
            "requires_building": b.requires_building,
            "power_consumption": b.power_consumption,
            "power_production": b.power_production,
        })
    return success(items)


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


@router.get("/research", response_model=None)
async def research_catalog(session: SessionDep, player_id: CurrentPlayer) -> dict:
    """Return the catalog of all researchable techs plus the player's current research status.

    Each entry includes the tech's branch, tier, cost, prerequisites,
    what it unlocks, and the player's current status (locked / available /
    in_progress / completed).
    """
    cid = await _resolve_country(session, player_id)
    svc = ResearchService(session)
    # Index the player's existing research nodes by tech_key for quick lookup.
    nodes = {n.key: n for n in await svc.repo.list_by_country(cid)}

    items = []
    for key, t in sorted(game_data.techs.items()):
        node = nodes.get(key)
        if node:
            status = node.status.value
        elif all(prereq in nodes and nodes[prereq].status.value == "completed"
                 for prereq in t.requires):
            status = "available"
        else:
            status = "locked"
        items.append({
            "key": t.key,
            "name": t.name,
            "branch": t.branch,
            "tier": t.tier,
            "description": t.description,
            "research_cost": t.research_cost,
            "research_time": t.research_time,
            "requires": t.requires,
            "effects": t.effects,
            "unlocks_buildings": t.unlocks_buildings,
            "unlocks_units": t.unlocks_units,
            "status": status,
        })
    return success(items)


@router.post("/research", response_model=None)
async def research(req: ResearchRequest, session: SessionDep, player_id: CurrentPlayer) -> dict:
    cid = await _resolve_country(session, player_id)
    svc = ResearchService(session)
    node = await svc.queue(cid, req.tech_key)
    return success({"tech": node.key, "status": node.status.value})
