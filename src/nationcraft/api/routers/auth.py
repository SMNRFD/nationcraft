"""Authentication endpoints."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from nationcraft.api.dependencies import CurrentPlayer, SessionDep
from nationcraft.api.schemas.envelope import success
from nationcraft.application.dto.auth import (
    LoginRequest,
    LogoutRequest,
    RefreshRequest,
    RegisterRequest,
    TokenResponse,
    UpdateLocaleRequest,
)
from nationcraft.application.services import AuthService

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
