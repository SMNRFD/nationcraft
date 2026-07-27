"""Market endpoints."""
from __future__ import annotations

from fastapi import APIRouter

from nationcraft.api.dependencies import CurrentPlayer, SessionDep
from nationcraft.api.schemas.envelope import success
from nationcraft.application.dto.game import MarketOrderRequest
from nationcraft.application.services import MarketService
from nationcraft.infrastructure.db.models import PlayerModel

router = APIRouter(prefix="/market", tags=["market"])


async def _resolve_country(session, player_id: int) -> tuple[int, int]:  # type: ignore[no-untyped-def]
    p = await session.get(PlayerModel, player_id)
    if not p or not p.country_id or not p.world_id:
        from nationcraft.core.exceptions import GameRuleError
        raise GameRuleError("player has no country")
    return p.country_id, p.world_id


@router.get("/orders", response_model=None)
async def list_orders(session: SessionDep, player_id: CurrentPlayer) -> dict:
    cid, _ = await _resolve_country(session, player_id)
    svc = MarketService(session)
    rows = await svc.list_country_orders(cid)
    return success([{
        "id": o.id, "side": o.side, "resource_key": o.resource_key,
        "quantity": o.quantity, "unit_price": o.unit_price,
        "filled_quantity": o.filled_quantity, "status": o.status,
    } for o in rows])


@router.post("/order", response_model=None)
async def place_order(
    req: MarketOrderRequest, session: SessionDep, player_id: CurrentPlayer
) -> dict:
    cid, wid = await _resolve_country(session, player_id)
    svc = MarketService(session)
    order = await svc.place_order(
        world_id=wid, country_id=cid, side=req.side,
        resource_key=req.resource_key, quantity=req.quantity,
        unit_price=req.unit_price, expires_in_seconds=req.expires_in_seconds,
    )
    return success({
        "id": order.id, "status": order.status,
        "filled_quantity": order.filled_quantity,
    })


@router.post("/cancel/{order_id}", response_model=None)
async def cancel_order(
    order_id: int, session: SessionDep, player_id: CurrentPlayer
) -> dict:
    cid, _ = await _resolve_country(session, player_id)
    svc = MarketService(session)
    await svc.cancel_order(cid, order_id)
    return success({"ok": True})
