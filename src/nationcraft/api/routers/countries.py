"""Country endpoints: list, select, snapshot."""
from __future__ import annotations

from fastapi import APIRouter

from nationcraft.api.dependencies import CurrentPlayer, SessionDep
from nationcraft.api.schemas.envelope import success
from nationcraft.application.services import CountryService
from nationcraft.infrastructure.db.models import PlayerModel

router = APIRouter(prefix="/countries", tags=["countries"])


@router.get("/available/{world_id}", response_model=None)
async def list_available(
    world_id: int, session: SessionDep, player_id: CurrentPlayer
) -> dict:
    svc = CountryService(session)
    rows = await svc.list_available(world_id)
    return success([c.model_dump(mode="json") for c in rows])


@router.get("/world/{world_id}", response_model=None)
async def list_by_world(
    world_id: int, session: SessionDep, player_id: CurrentPlayer
) -> dict:
    svc = CountryService(session)
    rows = await svc.list_by_world(world_id)
    return success([c.model_dump(mode="json") for c in rows])


@router.post("/select", response_model=None)
async def select_country(
    payload: dict, session: SessionDep, player_id: CurrentPlayer
) -> dict:
    svc = CountryService(session)
    result = await svc.select_country(
        player_id=player_id,
        world_id=int(payload["world_id"]),
        country_code=payload["country_code"],
    )
    return success(result.model_dump(mode="json"))


@router.post("/abandon", response_model=None)
async def abandon_country(
    session: SessionDep, player_id: CurrentPlayer
) -> dict:
    svc = CountryService(session)
    await svc.abandon_country(player_id)
    return success({"ok": True})


@router.get("/me", response_model=None)
async def my_country(session: SessionDep, player_id: CurrentPlayer) -> dict:
    p = await session.get(PlayerModel, player_id)
    if not p or not p.country_id:
        return success(None)
    svc = CountryService(session)
    snapshot = await svc.snapshot(p.country_id)
    return success(snapshot)


@router.get("/{country_id}", response_model=None)
async def get_country(
    country_id: int, session: SessionDep, player_id: CurrentPlayer
) -> dict:
    svc = CountryService(session)
    c = await svc.get_country(country_id)
    return success(c.model_dump(mode="json"))
