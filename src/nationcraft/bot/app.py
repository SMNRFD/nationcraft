"""aiogram bot application factory & run entrypoint."""
from __future__ import annotations

import asyncio
from contextlib import suppress
from typing import TYPE_CHECKING

import aiohttp
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramNetworkError, TelegramBadRequest
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import ErrorEvent

from nationcraft.bot.api_client import api_client
from nationcraft.bot.handlers.callbacks import router as callbacks_router
from nationcraft.bot.handlers.commands import router as commands_router
from nationcraft.bot.middleware.auth import AuthMiddleware, RateLimitMiddleware
from nationcraft.core.config import settings
from nationcraft.core.logging import configure_logging, get_logger

if TYPE_CHECKING:
    pass

log = get_logger(__name__)

# Module-level reference to the auth middleware so handlers can
# invalidate the locale cache after a successful /language change.
_auth_middleware: AuthMiddleware | None = None


def build_dispatcher() -> Dispatcher:
    global _auth_middleware
    dp = Dispatcher(storage=MemoryStorage())
    # Use the same AuthMiddleware instance for both message and callback
    # so the locale cache is shared.
    _auth_middleware = AuthMiddleware(api_client)
    dp.message.middleware(_auth_middleware)
    dp.callback_query.middleware(_auth_middleware)
    dp.message.middleware(RateLimitMiddleware())
    dp.callback_query.middleware(RateLimitMiddleware())
    dp.include_router(commands_router)
    dp.include_router(callbacks_router)

    # Global error handler — catches exceptions from ALL handlers so
    # they don't crash the polling loop. The most common errors are:
    #   • TelegramNetworkError (WinError 64, connection reset) — log
    #     a concise warning and move on; aiogram will retry the next
    #     update automatically.
    #   • TelegramBadRequest (can't parse entities) — already handled
    #     by safe_send, but if one slips through we log it here.
    @dp.error()
    async def on_error(event: ErrorEvent) -> None:
        exc = event.exception
        update = event.update
        update_id = update.update_id if update else "?"

        if isinstance(exc, TelegramNetworkError):
            # Network errors are transient (TCP reset, DNS timeout, etc.)
            # — log a SHORT message (not the full traceback) and let
            # aiogram continue polling.
            msg = str(exc)[:150]
            log.warning("bot.network_error", update_id=update_id, error=msg)
            return

        if isinstance(exc, TelegramBadRequest):
            msg = str(exc)[:150]
            if "message is not modified" in msg.lower():
                log.debug("bot.edit.unchanged", update_id=update_id)
                return
            if "query is too old" in msg.lower() or "query id is invalid" in msg.lower():
                log.debug("bot.callback.expired", update_id=update_id)
                return
            log.warning("bot.telegram_bad_request", update_id=update_id, error=msg)
            return

        # All other exceptions: log the full traceback for debugging
        # but DON'T crash the bot.
        log.exception("bot.unhandled_error", update_id=update_id, error=str(exc)[:300])

    return dp


def _build_aiohttp_session() -> aiohttp.ClientSession:
    """Build an aiohttp session with proxy support and resilient timeouts.

    For users in regions where api.telegram.org is blocked or throttled
    (Iran, China, Russia, etc.), set ``TELEGRAM_PROXY`` in .env:
      TELEGRAM_PROXY=socks5://127.0.0.1:1080
      TELEGRAM_PROXY=http://127.0.0.1:8080
    """
    # Total timeout: 30s connect, 60s total (Telegram can be slow on
    # poor networks — the default 5s was too short and caused WinError
    # 10054 on every long-poll cycle).
    timeout = aiohttp.ClientTimeout(total=60.0, connect=30.0, sock_connect=30.0, sock_read=30.0)

    # TCP connector with keepalive and generous limits.
    connector = aiohttp.TCPConnector(
        limit=20,
        limit_per_host=10,
        keepalive_timeout=30,
        enable_cleanup_closed=True,
        force_close=False,
    )

    proxy = settings.TELEGRAM_PROXY or None
    if proxy:
        log.info("bot.proxy.configured", proxy=proxy[:50])

    # Note: aiohttp uses the ``proxy`` parameter on each request, not
    # on the session. aiogram passes it through via Bot(session=...).
    # We'll set it on the session for non-aiogram requests.
    return aiohttp.ClientSession(timeout=timeout, connector=connector)


async def run_bot(use_webhook: bool = False) -> None:
    configure_logging(settings.LOG_LEVEL, settings.LOG_FORMAT)
    if not settings.TELEGRAM_BOT_TOKEN:
        raise RuntimeError("TELEGRAM_BOT_TOKEN not set")

    # Use parse_mode=None (plain text) as the DEFAULT — individual
    # handlers that need Markdown explicitly pass parse_mode="Markdown"
    # through safe_send(). This prevents TelegramBadRequest
    # "can't parse entities" when user-supplied content (usernames,
    # country names, etc.) contains Markdown special chars like _ or *.
    bot = Bot(
        token=settings.TELEGRAM_BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=None),
    )
    dp = build_dispatcher()

    # Configure the bot's HTTP session with proxy + resilient timeouts.
    # This must happen BEFORE start_polling so the first get_me() uses
    # the new session.
    session = _build_aiohttp_session()
    bot.session._connector = session.connector
    bot.session._timeout = session.timeout
    # Store proxy for aiogram to use on every request.
    if settings.TELEGRAM_PROXY:
        bot.session._default_proxy = settings.TELEGRAM_PROXY
    await session.close()  # we only needed its config, not the session itself

    if use_webhook and settings.TELEGRAM_WEBHOOK_URL:
        await bot.set_webhook(
            settings.TELEGRAM_WEBHOOK_URL,
            secret_token=settings.TELEGRAM_WEBHOOK_SECRET,
        )
        log.info("bot.webhook.set", url=settings.TELEGRAM_WEBHOOK_URL)
    else:
        me = await bot.get_me()
        log.info("bot.start", username=me.username, id=me.id)
        try:
            await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
        finally:
            await bot.session.close()
            await api_client.close()
