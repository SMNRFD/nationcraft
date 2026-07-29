"""aiogram bot application factory & run entrypoint."""
from __future__ import annotations

import asyncio
from contextlib import suppress
from typing import TYPE_CHECKING

import aiohttp
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.client.telegram import TelegramAPIServer
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

    Returns a session ONLY for its config (connector + timeout) — the
    caller closes it immediately. The bot itself uses a properly
    configured ``AiohttpSession`` passed via ``Bot(session=...)`` (see
    ``run_bot``).
    """
    # Total timeout for individual HTTP requests to Telegram.
    # The default aiogram uses is 60s — too long on a throttled
    # network, because a single ``message.answer()`` can block for
    # 60s, which makes aiogram queue all subsequent updates for that
    # chat. On a slow Iranian network this compounds to 19-38s update
    # durations and WinError 10054 (the OS forcibly closes the
    # connection before aiogram's 60s timeout fires).
    #
    # 15s is short enough that the bot recovers and processes queued
    # updates within a reasonable window, and long enough that a
    # legitimately slow Telegram API response still has time to
    # arrive. Telegram's own getUpdates long-poll uses 30s, so 15s
    # is below that and won't race with the long-poll itself.
    total = settings.TELEGRAM_REQUEST_TIMEOUT
    connect = min(total, 15.0)
    timeout = aiohttp.ClientTimeout(total=total, connect=connect, sock_connect=connect, sock_read=total)

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

    return aiohttp.ClientSession(timeout=timeout, connector=connector)


def _build_aiogram_session() -> AiohttpSession:
    """Build an aiogram AiohttpSession with proxy + per-request timeout
    set PROPERLY (via constructor, not by mutating private attrs).

    The previous implementation tried to set ``bot.session._connector``
    and ``bot.session._timeout`` AFTER the bot was created. That had
    NO effect because ``AiohttpSession`` doesn't expose those attrs —
    it constructs the underlying ``aiohttp.ClientSession`` lazily via
    ``create_session()``, reading from ``self._connector_init`` and
    ``self.timeout`` (both set at construction time).

    Result: the bot was using aiogram's DEFAULT 60s timeout, which on
    a throttled Iranian network caused each ``message.answer()`` to
    block for 60s (or get forcibly closed by the OS at ~5s with
    WinError 10054), compounding into the reported 19-38s update
    durations.

    Now we pass a properly constructed ``AiohttpSession`` to
    ``Bot(session=...)`` so the timeout and proxy actually take
    effect on every request aiogram makes.
    """
    # Per-request timeout (was hardcoded 60s in aiogram's default).
    # Make sure aiohttp-socks is installed if a SOCKS proxy is set.
    proxy = settings.TELEGRAM_PROXY or None
    return AiohttpSession(
        proxy=proxy,
        timeout=settings.TELEGRAM_REQUEST_TIMEOUT,
    )


def _build_api_server() -> TelegramAPIServer:
    """Build the TelegramAPIServer based on ``settings.TELEGRAM_API_BASE``.

    Defaults to ``https://api.telegram.org`` (production). When set to
    a local URL (e.g. ``http://localhost:8081``), the bot will talk to
    a local mock Telegram Bot API server instead — this is how the
    end-to-end tests exercise the bot's real HTTP interaction without
    needing network access to api.telegram.org.

    ``TelegramAPIServer.from_base`` expects just the origin (e.g.
    ``http://localhost:8081``) and appends ``/bot{token}/{method}``
    itself. We strip any existing suffix to avoid doubling it.
    """
    base = settings.TELEGRAM_API_BASE or "https://api.telegram.org"
    base = base.rstrip("/")
    # Strip any existing /bot{token}/{method} suffix — from_base will
    # re-add it. This makes the setting idempotent whether the user
    # provides just the origin or the full template.
    if base.endswith("/bot{token}/{method}"):
        base = base[: -len("/bot{token}/{method}")]
    return TelegramAPIServer.from_base(base)


async def run_bot(use_webhook: bool = False) -> None:
    configure_logging(settings.LOG_LEVEL, settings.LOG_FORMAT)
    if not settings.TELEGRAM_BOT_TOKEN:
        raise RuntimeError("TELEGRAM_BOT_TOKEN not set")

    # Use parse_mode=None (plain text) as the DEFAULT — individual
    # handlers that need Markdown explicitly pass parse_mode="Markdown"
    # through safe_send(). This prevents TelegramBadRequest
    # "can't parse entities" when user-supplied content (usernames,
    # country names, etc.) contains Markdown special chars like _ or *.
    #
    # IMPORTANT: pass a properly-constructed AiohttpSession so the
    # per-request timeout and proxy actually take effect. The previous
    # implementation set ``bot.session._connector`` and ``_timeout``
    # AFTER the bot was created — but AiohttpSession doesn't expose
    # those attrs, so the settings were silently ignored and aiogram's
    # default 60s timeout was used. On a throttled Iranian network,
    # this caused each message.answer() to block for 60s (or get
    # forcibly closed by the OS at ~5s with WinError 10054), which
    # compounded into the reported 19-38s update durations.
    session = _build_aiogram_session()
    bot = Bot(
        token=settings.TELEGRAM_BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=None),
        session=session,
    )
    # Honor TELEGRAM_API_BASE so the bot can be pointed at a local mock
    # Telegram Bot API server for end-to-end testing (bypassing the real
    # api.telegram.org, which is blocked in some regions like Iran).
    api_server = _build_api_server()
    bot.session.api = api_server
    if settings.TELEGRAM_API_BASE and settings.TELEGRAM_API_BASE != "https://api.telegram.org":
        log.info("bot.api_base.custom", base=settings.TELEGRAM_API_BASE)
    dp = build_dispatcher()

    if settings.TELEGRAM_PROXY:
        log.info("bot.proxy.configured", proxy=settings.TELEGRAM_PROXY[:50])
    else:
        # Loud warning for users in regions where api.telegram.org is
        # throttled (Iran, China, Russia, etc.). Without a proxy, the
        # bot will see WinError 10054 / "Cannot connect to host
        # api.telegram.org:443" on every long-poll cycle.
        log.warning(
            "bot.no_proxy_set",
            hint=(
                "Set TELEGRAM_PROXY in .env if you're in a region where "
                "api.telegram.org is blocked/throttled (Iran, China, "
                "Russia). Examples: "
                "TELEGRAM_PROXY=socks5://127.0.0.1:1080  OR  "
                "TELEGRAM_PROXY=http://127.0.0.1:8080"
            ),
        )

    if use_webhook and settings.TELEGRAM_WEBHOOK_URL:
        await bot.set_webhook(
            settings.TELEGRAM_WEBHOOK_URL,
            secret_token=settings.TELEGRAM_WEBHOOK_SECRET,
        )
        log.info("bot.webhook.set", url=settings.TELEGRAM_WEBHOOK_URL)
        try:
            await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
        finally:
            await bot.session.close()
            await api_client.close()
    else:
        # ---- Retry getMe with backoff ----
        # On a throttled network (Iran, China, Russia), the initial
        # ``bot.get_me()`` call can time out. Previously, this raised
        # ``TelegramNetworkError`` which propagated up and killed the
        # entire process (``main.task.exited error='HTTP Client says -
        # Request timeout error'``). The API and worker were then
        # shut down too, even though they were perfectly healthy.
        #
        # Now we retry up to 5 times with exponential backoff. If all
        # retries fail, we enter "degraded polling" mode where we
        # start polling anyway — aiogram's polling loop has its own
        # built-in retry logic for network errors.
        #
        # CRITICAL: The entire block is wrapped in try/finally so the
        # aiohttp session is ALWAYS closed, even if getMe/polling
        # raises. Previously, when getMe raised, the session was
        # leaked → "Unclosed client session" warning.
        try:
            me = None
            max_getme_retries = 5
            for attempt in range(max_getme_retries):
                try:
                    me = await bot.get_me()
                    break
                except TelegramNetworkError as exc:
                    if attempt < max_getme_retries - 1:
                        backoff = min(2 ** attempt, 30)  # 1, 2, 4, 8, 16s
                        log.warning(
                            "bot.getme.retry",
                            attempt=attempt + 1,
                            max=max_getme_retries,
                            backoff_seconds=backoff,
                            error=str(exc)[:150],
                        )
                        await asyncio.sleep(backoff)
                    else:
                        log.error(
                            "bot.getme.failed",
                            hint=(
                                "Cannot reach api.telegram.org after "
                                f"{max_getme_retries} attempts. The bot will "
                                "keep retrying via the polling loop. If you're "
                                "in a region where Telegram is blocked (Iran, "
                                "China, Russia), set TELEGRAM_PROXY in .env: "
                                "TELEGRAM_PROXY=socks5://127.0.0.1:1080"
                            ),
                        )
                except Exception as exc:  # noqa: BLE001
                    if attempt < max_getme_retries - 1:
                        log.warning(
                            "bot.getme.retry",
                            attempt=attempt + 1,
                            max=max_getme_retries,
                            error=str(exc)[:150],
                        )
                        await asyncio.sleep(2 ** attempt)
                    else:
                        log.error("bot.getme.failed", error=str(exc)[:200])

            if me is not None:
                log.info("bot.start", username=me.username, id=me.id)
            else:
                log.warning("bot.start.degraded", reason="getMe failed, starting polling anyway")

            # ``start_polling`` has its own retry logic for network errors
            # — it will keep trying getUpdates with backoff. This is the
            # correct behavior: the bot stays alive and recovers when the
            # network comes back.
            await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
        finally:
            # ALWAYS close the session, even if getMe/polling raised.
            # This prevents the "Unclosed client session" warning.
            await bot.session.close()
            await api_client.close()
