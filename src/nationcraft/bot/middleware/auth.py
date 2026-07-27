"""Authentication & i18n middleware for the bot."""
from __future__ import annotations

from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, User

from nationcraft.core.config import settings
from nationcraft.core.exceptions import NationCraftError
from nationcraft.core.logging import get_logger
from nationcraft.infrastructure.security.rate_limit import (
    InMemoryRateLimiter,
    RateLimiter,
)

log = get_logger(__name__)


class AuthMiddleware(BaseMiddleware):
    """Attaches ``telegram_id``, ``api_token``, and ``locale`` to handler data.

    The locale is resolved in this priority order:
    1. The player's locale as stored in the database (via ``GET /auth/me``).
    2. The Telegram client's ``language_code``.
    3. ``settings.DEFAULT_LOCALE``.

    The DB lookup is cached per-telegram-id for 5 minutes to avoid
    hitting the API on every message.
    """

    _LOCALE_CACHE_TTL_SECONDS = 300

    def __init__(self, api_client) -> None:  # type: ignore[no-untyped-def]
        self.api = api_client
        self._locale_cache: dict[int, tuple[float, str]] = {}

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
        data["locale"] = await self._resolve_locale(user)
        return await handler(event, data)

    async def _resolve_locale(self, user: User) -> str:
        """Resolve the player's preferred locale."""
        import time

        # Check cache first.
        cached = self._locale_cache.get(user.id)
        if cached and time.time() - cached[0] < self._LOCALE_CACHE_TTL_SECONDS:
            return cached[1]

        # Try to fetch from API.
        locale: str | None = None
        if self.api.get_token(user.id):
            try:
                player = await self.api.get_me(user.id)
                if player and player.get("locale"):
                    locale = player["locale"]
            except NationCraftError:
                pass  # fall through to language_code

        # Fall back to Telegram client language, then default.
        if not locale:
            locale = (user.language_code or settings.DEFAULT_LOCALE)[:2]

        # Cache and return.
        self._locale_cache[user.id] = (time.time(), locale)
        return locale

    def invalidate_locale(self, telegram_id: int) -> None:
        """Force a re-fetch on next message (call after updating locale)."""
        self._locale_cache.pop(telegram_id, None)


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
