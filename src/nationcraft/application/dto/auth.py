"""DTOs for auth and player flows."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class RegisterRequest(BaseModel):
    telegram_id: int
    username: str | None = None
    locale: str = "en"
    password: str = Field(min_length=8, max_length=128)


class LoginRequest(BaseModel):
    telegram_id: int
    password: str


class RefreshRequest(BaseModel):
    refresh_token: str


class LogoutRequest(BaseModel):
    refresh_token: str


class PlayerDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    telegram_id: int
    username: str | None
    locale: str
    role: str
    is_banned: bool
    world_id: int | None
    country_id: int | None
    last_login_at: datetime | None
    created_at: datetime


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "Bearer"
    expires_in: int
    player: PlayerDTO
