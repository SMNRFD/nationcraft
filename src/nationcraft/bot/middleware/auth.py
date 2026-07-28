"""Authentication & i18n middleware for the bot.

Key design choices
------------------
* The locale cache is populated IMMEDIATELY with a fast fallback (Telegram
  client language or default locale) BEFORE any network call. The previous
  implementation awaited ``get_me`` on cache-miss + token-present, which
  blocked the entire handler chain for up to 15s when the API was
  overloaded — directly causing the reported "15-17s update durations" and
  the "Please send your password" prompt arriving AFTER a timeout error.
* Background refresh: if we have a token but the cache is missing/stale,
  we kick off an async ``get_me`` and update the cache when it completes.
  We never block the handler chain on it.
* Stale token detection: if ``get_me`` fails with a 401 (which now also
  evicts the token via ApiClient._request), we invalidate the cache so the
  next message doesn't try the same dead token.
* ``is_admin`` is True if the user's Telegram ID is in ``settings.admin_ids``
  (a comma-separated list from ``TELEGRAM_ADMIN_IDS`` env var).
"""
from __future__ import annotations

import asyncio
import time
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
    """Attaches ``telegram_id``, ``api_token``, ``locale``, and ``is_admin`` to handler data.

    The locale is resolved in this priority order:
    1. The cached player's locale (refreshed asynchronously in the background).
    2. The Telegram client's ``language_code``.
    3. ``settings.DEFAULT_LOCALE``.

    The DB lookup is cached per-telegram-id for 5 minutes. The cache is
    populated with the FALLBACK immediately on cache-miss (so the handler
    chain never blocks on a network call) and refreshed asynchronously.
    """

    _LOCALE_CACHE_TTL_SECONDS = 300

    def __init__(self, api_client) -> None:  # type: ignore[no-untyped-def]
        self.api = api_client
        # telegram_id -> (timestamp, locale, was_real_lookup)
        self._locale_cache: dict[int, tuple[float, str, bool]] = {}
        # In-flight refresh tasks, to dedupe concurrent refreshes.
        self._refresh_tasks: dict[int, asyncio.Task] = {}

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
        data["locale"] = self._resolve_locale_fast(user)
        data["is_admin"] = user.id in settings.admin_ids

        # Kick off a background refresh if needed (non-blocking).
        self._maybe_refresh_locale(user.id)

        return await handler(event, data)

    def _resolve_locale_fast(self, user: User) -> str:
        """Return a locale immediately, populating the cache with a fallback
        if no real lookup has been done yet. Never blocks on the network.
        """
        cached = self._locale_cache.get(user.id)
        if cached and time.time() - cached[0] < self._LOCALE_CACHE_TTL_SECONDS:
            return cached[1]
        # Cache miss or expired — return the fast fallback immediately.
        fallback = (user.language_code or settings.DEFAULT_LOCALE)[:2]
        # Support: if the user's Telegram language is "fa-IR", we want "fa".
        # Already handled by [:2] slice above.
        if not settings.supported_locales_list or fallback not in settings.supported_locales_list:
            fallback = settings.DEFAULT_LOCALE
        # Store as a non-real lookup so the background refresh knows to retry.
        self._locale_cache[user.id] = (time.time(), fallback, False)
        return fallback

    def _maybe_refresh_locale(self, telegram_id: int) -> None:
        """Kick off an async locale refresh if we have a token AND the cache
        is stale (or was only ever populated with the fallback). Non-blocking.
        """
        if not self.api.get_token(telegram_id):
            return
        cached = self._locale_cache.get(telegram_id)
        # If we have a fresh real lookup, no need to refresh.
        if cached and cached[2] and time.time() - cached[0] < self._LOCALE_CACHE_TTL_SECONDS:
            return
        # Dedupe: if a refresh is already in-flight, don't start another.
        existing = self._refresh_tasks.get(telegram_id)
        if existing is not None and not existing.done():
            return
        try:
            task = asyncio.create_task(self._refresh_locale_task(telegram_id))
            self._refresh_tasks[telegram_id] = task
        except RuntimeError:
            # No running loop (e.g., in tests) — skip.
            pass

    async def _refresh_locale_task(self, telegram_id: int) -> None:
        """Background task: fetch the player's locale from the API and
        update the cache. On auth failure, the API client already evicted
        the stale token; we just leave the fallback in the cache.
        """
        try:
            player = await self.api.get_me(telegram_id)
            if player and player.get("locale"):
                # Real lookup succeeded — cache the real locale.
                self._locale_cache[telegram_id] = (
                    time.time(), player["locale"], True
                )
        except NationCraftError as exc:
            log.debug("bot.locale.refresh_failed", telegram_id=telegram_id, error=str(exc)[:100])
        except Exception as exc:  # noqa: BLE001
            log.debug("bot.locale.refresh_failed", telegram_id=telegram_id, error=str(exc)[:100])
        finally:
            self._refresh_tasks.pop(telegram_id, None)

    def invalidate_locale(self, telegram_id: int) -> None:
        """Force a re-fetch on next message (call after updating locale).

        Also drops any in-flight refresh task for this user.
        """
        self._locale_cache.pop(telegram_id, None)
        task = self._refresh_tasks.pop(telegram_id, None)
        if task is not None and not task.done():
            task.cancel()


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
