"""aiogram bot application factory & run entrypoint."""
from __future__ import annotations

import asyncio

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage

from nationcraft.bot.api_client import api_client
from nationcraft.bot.handlers.callbacks import router as callbacks_router
from nationcraft.bot.handlers.commands import router as commands_router
from nationcraft.bot.middleware.auth import AuthMiddleware, RateLimitMiddleware
from nationcraft.core.config import settings
from nationcraft.core.logging import configure_logging, get_logger

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
    return dp


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

    # Pre-flight check: verify the API is reachable before starting
    # polling. Wait up to 30 seconds for the API to come up (it takes
    # ~10s to start: plugin loading, DB check, Redis check, i18n load).
    # Previously this checked once with a 5s timeout and failed every
    # time when bot+API share a process (the API hadn't started yet).
    import httpx
    api_reachable = False
    for attempt in range(15):  # 15 * 2s = 30s max
        try:
            async with httpx.AsyncClient(timeout=3.0) as _c:
                r = await _c.get(f"{api_client.base_url}/health")
                if r.status_code == 200:
                    api_reachable = True
                    log.info("bot.api.reachable", url=api_client.base_url, attempts=attempt + 1)
                    break
        except Exception:
            pass
        await asyncio.sleep(2)

    if not api_reachable:
        log.warning(
            "bot.api.unreachable",
            url=api_client.base_url,
            hint="Run `python main.py --local` (not --only bot) "
                 "and `python main.py --local --initdb` first.",
        )

    if use_webhook and settings.TELEGRAM_WEBHOOK_URL:
        await bot.set_webhook(
            settings.TELEGRAM_WEBHOOK_URL,
            secret_token=settings.TELEGRAM_WEBHOOK_SECRET,
        )
        log.info("bot.webhook.set", url=settings.TELEGRAM_WEBHOOK_URL)
    else:
        me = await bot.get_me()
        log.info("bot.start", username=me.username, id=me.id, api_reachable=api_reachable)
        try:
            await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
        finally:
            await bot.session.close()
            await api_client.close()
