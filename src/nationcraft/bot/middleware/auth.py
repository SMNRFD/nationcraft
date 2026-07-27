"""Authentication & i18n middleware for the bot."""
from __future__ import annotations

from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, User

from nationcraft.core.exceptions import AuthenticationError
from nationcraft.core.logging import get_logger
from nationcraft.infrastructure.security.rate_limit import (
    InMemoryRateLimiter,
    RateLimiter,
)
from nationcraft.core.config import settings

log = get_logger(__name__)


class AuthMiddleware(BaseMiddleware):
    """Ensures the Telegram user is registered; attaches player_id and API token."""

    def __init__(self, api_client) -> None:  # type: ignore[no-untyped-def]
        self.api = api_client

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        user: User | None = data.get("event_from_user")
        if user is None:
            return await handler(event, data)
        token = self.api.get_token(user.id)
        data["telegram_id"] = user.id
        data["api_token"] = token
        data["locale"] = (user.language_code or settings.DEFAULT_LOCALE)[:2]
        return await handler(event, data)


class RateLimitMiddleware(BaseMiddleware):
    """Per-user rate limiting for bot interactions."""

    def __init__(self) -> None:
        self.limiter: RateLimiter = InMemoryRateLimiter()

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        user: User | None = data.get("event_from_user")
        if user is not None:
            await self.limiter.check(
                f"bot:{user.id}",
                settings.RATE_LIMIT_BOT_PER_USER_PER_MINUTE,
                60,
            )
        return await handler(event, data)
