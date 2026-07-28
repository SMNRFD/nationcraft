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

    bot = Bot(
        token=settings.TELEGRAM_BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.MARKDOWN),
    )
    dp = build_dispatcher()

    # Pre-flight check: verify the API is reachable before starting
    # polling. If the API is down, every bot command will fail with
    # "Cannot reach the game server" — better to warn now so the user
    # knows to fix it.
    import httpx
    api_reachable = False
    try:
        async with httpx.AsyncClient(timeout=5.0) as _c:
            r = await _c.get(f"{api_client.base_url}/health")
            if r.status_code == 200:
                api_reachable = True
                log.info("bot.api.reachable", url=api_client.base_url)
            else:
                log.warning(
                    "bot.api.unreachable",
                    url=api_client.base_url,
                    status=r.status_code,
                    hint="Run `python main.py --local` (not --only bot) "
                         "and `python main.py --local --initdb` first.",
                )
    except Exception as exc:  # noqa: BLE001
        log.warning(
            "bot.api.unreachable",
            url=api_client.base_url,
            error=str(exc)[:200],
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
