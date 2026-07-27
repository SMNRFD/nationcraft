"""Admin endpoints: broadcast, ban, manage plugins, analytics."""
from __future__ import annotations

from fastapi import APIRouter

from nationcraft.api.dependencies import CurrentPlayer, SessionDep
from nationcraft.api.schemas.envelope import success
from nationcraft.application.dto.game import BroadcastRequest
from nationcraft.application.services import AdminService, GameDataService
from nationcraft.core.plugins import PluginRegistry
from nationcraft.domain.enums import PlayerRole
from nationcraft.infrastructure.db.models import PlayerModel
from nationcraft.infrastructure.observability import metrics

router = APIRouter(prefix="/admin", tags=["admin"])


def _require_admin(player_id: int) -> None:
    """Inline admin check (called within endpoints; we already have player_id)."""
    # Real authorization is done via JWT role claim; here we re-check DB for safety.
    pass


@router.post("/broadcast", response_model=None)
async def broadcast(
    req: BroadcastRequest, session: SessionDep, player_id: CurrentPlayer
) -> dict:
    p = await session.get(PlayerModel, player_id)
    if p is None or p.role not in (PlayerRole.ADMIN.value, PlayerRole.OWNER.value):
        from nationcraft.core.exceptions import AuthorizationError
        raise AuthorizationError("admin only")
    svc = AdminService(session)
    n = await svc.broadcast(req.message, req.locale)
    return success({"recipients": n})


@router.post("/ban/{target_id}", response_model=None)
async def ban_player(
    target_id: int, session: SessionDep, player_id: CurrentPlayer
) -> dict:
    p = await session.get(PlayerModel, player_id)
    if p is None or p.role not in (PlayerRole.ADMIN.value, PlayerRole.OWNER.value):
        from nationcraft.core.exceptions import AuthorizationError
        raise AuthorizationError("admin only")
    svc = AdminService(session)
    await svc.ban_player(target_id)
    return success({"ok": True})


@router.post("/unban/{target_id}", response_model=None)
async def unban_player(
    target_id: int, session: SessionDep, player_id: CurrentPlayer
) -> dict:
    p = await session.get(PlayerModel, player_id)
    if p is None or p.role not in (PlayerRole.ADMIN.value, PlayerRole.OWNER.value):
        from nationcraft.core.exceptions import AuthorizationError
        raise AuthorizationError("admin only")
    svc = AdminService(session)
    await svc.unban_player(target_id)
    return success({"ok": True})


@router.get("/plugins", response_model=None)
async def list_plugins(session: SessionDep, player_id: CurrentPlayer) -> dict:
    p = await session.get(PlayerModel, player_id)
    if p is None or p.role not in (PlayerRole.ADMIN.value, PlayerRole.OWNER.value):
        from nationcraft.core.exceptions import AuthorizationError
        raise AuthorizationError("admin only")
    rows = PluginRegistry.instance().all()
    return success([{
        "id": r.manifest.id, "name": r.manifest.name,
        "version": r.manifest.version, "state": r.state.value,
        "error": r.error,
    } for r in rows])


@router.post("/plugins/{plugin_id}/{action}", response_model=None)
async def toggle_plugin(
    plugin_id: str, action: str, session: SessionDep, player_id: CurrentPlayer
) -> dict:
    p = await session.get(PlayerModel, player_id)
    if p is None or p.role not in (PlayerRole.ADMIN.value, PlayerRole.OWNER.value):
        from nationcraft.core.exceptions import AuthorizationError
        raise AuthorizationError("admin only")
    if action == "disable":
        PluginRegistry.instance().unload(plugin_id)
        svc = AdminService(session)
        await svc.set_plugin_enabled(plugin_id, False)
    else:
        from nationcraft.core.exceptions import ValidationError
        raise ValidationError(f"unsupported action: {action}")
    return success({"ok": True})


@router.post("/game-data/reload", response_model=None)
async def reload_game_data(session: SessionDep, player_id: CurrentPlayer) -> dict:
    p = await session.get(PlayerModel, player_id)
    if p is None or p.role not in (PlayerRole.ADMIN.value, PlayerRole.OWNER.value):
        from nationcraft.core.exceptions import AuthorizationError
        raise AuthorizationError("admin only")
    svc = GameDataService(session)
    counts = await svc.load_all()
    return success(counts)


@router.get("/metrics", response_model=None)
async def get_metrics(session: SessionDep, player_id: CurrentPlayer) -> dict:
    p = await session.get(PlayerModel, player_id)
    if p is None or p.role not in (PlayerRole.ADMIN.value, PlayerRole.OWNER.value):
        from nationcraft.core.exceptions import AuthorizationError
        raise AuthorizationError("admin only")
    return success(metrics.snapshot())
