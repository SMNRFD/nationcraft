"""Authentication endpoints."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from nationcraft.api.dependencies import CurrentPlayer, SessionDep
from nationcraft.api.schemas.envelope import success
from nationcraft.application.dto.auth import (
    LoginRequest,
    LogoutRequest,
    PromoteAdminRequest,
    RefreshRequest,
    RegisterRequest,
    ResetPasswordRequest,
    TokenResponse,
    UpdateLocaleRequest,
)
from nationcraft.application.services import AuthService
from nationcraft.core.exceptions import AuthorizationError, ValidationError
from nationcraft.domain.enums import PlayerRole
from nationcraft.infrastructure.db.models import PlayerModel

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=None)
async def register(req: RegisterRequest, session: SessionDep) -> dict:
    svc = AuthService(session)
    result = await svc.register(req)
    return success(result.model_dump(mode="json"))


@router.post("/login", response_model=None)
async def login(req: LoginRequest, session: SessionDep) -> dict:
    svc = AuthService(session)
    result = await svc.login(req)
    return success(result.model_dump(mode="json"))


@router.post("/refresh", response_model=None)
async def refresh(req: RefreshRequest, session: SessionDep) -> dict:
    svc = AuthService(session)
    result = await svc.refresh(req)
    return success(result.model_dump(mode="json"))


@router.post("/logout", response_model=None)
async def logout(req: LogoutRequest, session: SessionDep) -> dict:
    svc = AuthService(session)
    await svc.logout(req)
    return success({"ok": True})


@router.get("/me", response_model=None)
async def get_me(session: SessionDep, player_id: CurrentPlayer) -> dict:
    """Return the current player's state (locale, role, etc.)."""
    svc = AuthService(session)
    player = await svc.get_player(player_id)
    return success(player.model_dump(mode="json"))


@router.post("/locale", response_model=None)
async def update_locale(
    req: UpdateLocaleRequest, session: SessionDep, player_id: CurrentPlayer
) -> dict:
    """Update the current player's preferred locale."""
    svc = AuthService(session)
    player = await svc.set_locale(player_id, req.locale)
    return success(player.model_dump(mode="json"))


@router.post("/reset-password", response_model=None)
async def reset_password(
    req: ResetPasswordRequest, session: SessionDep, player_id: CurrentPlayer
) -> dict:
    """Reset the current player's password.

    The caller must be authenticated (via JWT) and must provide their
    old password. The new password replaces the old one and all
    existing sessions are revoked.
    """
    svc = AuthService(session)
    # Ensure the caller is resetting their own password.
    caller = await session.get(PlayerModel, player_id)
    if caller is None or caller.telegram_id != req.telegram_id:
        raise AuthorizationError("can only reset your own password")
    await svc.reset_password(req.telegram_id, req.old_password, req.new_password)
    return success({"ok": True})


@router.post("/promote-admin", response_model=None)
async def promote_admin(
    req: PromoteAdminRequest, session: SessionDep, player_id: CurrentPlayer
) -> dict:
    """Promote a player to moderator/admin/owner. Only owners can call this."""
    from nationcraft.core.config import settings
    caller = await session.get(PlayerModel, player_id)
    if caller is None:
        raise AuthorizationError("not authenticated")
    # Only owners (or telegram admins configured via env) can promote.
    is_owner = caller.role == PlayerRole.OWNER.value
    is_telegram_admin = caller.telegram_id in settings.admin_ids
    if not (is_owner or is_telegram_admin):
        raise AuthorizationError("only owners can promote players")
    svc = AuthService(session)
    player = await svc.promote_to_admin(req.telegram_id, req.role)
    return success(player.model_dump(mode="json"))
