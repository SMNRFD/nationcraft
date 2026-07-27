"""Worlds endpoints."""
from __future__ import annotations

from fastapi import APIRouter, Query

from nationcraft.api.dependencies import CurrentPlayer, SessionDep
from nationcraft.api.schemas.envelope import success
from nationcraft.application.services import WorldService

router = APIRouter(prefix="/worlds", tags=["worlds"])


@router.get("", response_model=None)
async def list_worlds(
    session: SessionDep,
    player_id: CurrentPlayer,
    only_open: bool = Query(default=True),
) -> dict:
    svc = WorldService(session)
    if only_open:
        rows = await svc.list_open()
    else:
        rows = await svc.list_all_active()
    return success([w.model_dump(mode="json") for w in rows])


@router.get("/{world_id}", response_model=None)
async def get_world(world_id: int, session: SessionDep, player_id: CurrentPlayer) -> dict:
    svc = WorldService(session)
    w = await svc.get(world_id)
    return success(w.model_dump(mode="json"))
