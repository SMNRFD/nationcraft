#!/usr/bin/env python3
"""NationCraft — single-entrypoint launcher.

Runs the API, tick worker, and Telegram bot concurrently in **one**
process. Ideal for local development, single-container deployments,
and quick testing without docker-compose.

Usage
-----
Run everything (API + worker + bot)::

    python main.py

Run only one component::

    python main.py --only api
    python main.py --only worker
    python main.py --only bot

Initialize database first (migrate + seed worlds + load game data)::

    python main.py --initdb

Run migrations only::

    python main.py --migrate

Custom host/port::

    python main.py --host 0.0.0.0 --port 8000

Development mode (auto-reload on file changes)::

    python main.py --only api --reload

Bot in webhook mode (requires TELEGRAM_WEBHOOK_URL in .env)::

    python main.py --only bot --webhook

Environment
------------
All configuration is read from environment variables or a local
``.env`` file. See ``.env.example`` for the full list.

Notes
-----
- When running all components in one process, the API uses a single
  worker (no uvicorn pre-fork). This is fine for development and small
  deployments. For production with many players, prefer docker-compose
  so the API can scale to multiple workers independently.
- The bot is only started if ``TELEGRAM_BOT_TOKEN`` is set in the
  environment. Otherwise it's skipped with a warning.
- Press Ctrl+C to gracefully shut down all components.
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import os
import re
import signal
import sys
from pathlib import Path

# ── Windows event-loop fix ─────────────────────────────────────────────
# Python 3.8+ on Windows defaults to ProactorEventLoop, which has SERIOUS
# issues when multiple async I/O layers share one event loop:
#
#   • aiohttp (Telegram bot) + httpx (API client) + uvicorn (API server)
#     all in one process → TCP connections to localhost stall randomly.
#   • Symptoms: httpx.ReadTimeout (API call succeeds in 300ms but the
#     bot's httpx client never receives the response), TelegramNetworkError
#     [WinError 64] "The specified network name is no longer available",
#     update handling takes 20+ seconds.
#   • The root cause: ProactorEventLoop uses Windows IOCP which doesn't
#     handle mixed localhost TCP + outbound HTTPS well under contention.
#
# Fix: switch to SelectorEventLoop, which uses select() and handles
# mixed I/O correctly. This must be done BEFORE any asyncio code runs.
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

# Ensure src/ is importable when running from a non-installed checkout
# (e.g. python main.py without `pip install -e .`).
_SRC = Path(__file__).resolve().parent / "src"
if _SRC.exists() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from nationcraft.core.config import settings  # noqa: E402
from nationcraft.core.logging import configure_logging, get_logger  # noqa: E402

log = get_logger(__name__)


# ---------------------------------------------------------------------------
# Database helpers
# ---------------------------------------------------------------------------

def run_migrations() -> None:
    """Apply database schema.

    For PostgreSQL (production): use Alembic migrations.
    For SQLite (local dev / tests): use ``Base.metadata.create_all()``
    because Alembic's migration 0001 uses ``op.create_foreign_key()``
    which SQLite doesn't support without batch mode.
    """
    if settings.DATABASE_URL.startswith("sqlite"):
        # SQLite: just create all tables directly. Use a *fresh* engine
        # so we don't dispose the module-level engine that the API will
        # use moments later.
        import asyncio
        from sqlalchemy.ext.asyncio import create_async_engine
        from nationcraft.infrastructure.db.models import Base

        async def _create() -> None:
            eng = create_async_engine(settings.DATABASE_URL)
            async with eng.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
            await eng.dispose()

        asyncio.run(_create())
        log.info("migrations.applied", method="create_all", url="sqlite")
        return

    # PostgreSQL: use Alembic.
    from alembic.config import Config
    from alembic import command

    cfg = Config("alembic.ini")
    command.upgrade(cfg, "head")
    log.info("migrations.applied", method="alembic", url="postgresql")


async def initdb(load_data: bool = True) -> None:
    """Migrate + ensure at least one world exists + (optionally) load game data.

    Migrations are run in a worker thread (not the event loop) so that
    Alembic's internal ``asyncio.run()`` call doesn't conflict with the
    running loop.
    """
    import asyncio as _asyncio

    await _asyncio.to_thread(run_migrations)

    from nationcraft.application.services.game_data_service import GameDataService
    from nationcraft.application.services.world_service import WorldService
    from nationcraft.infrastructure.db.session import AsyncSessionLocal

    # NOTE: do NOT dispose the module-level engine here. The API will
    # reuse it moments later when it starts serving requests.
    async with AsyncSessionLocal() as session:
        ws = WorldService(session)
        await ws.ensure_worlds(capacity=settings.WORLD_PLAYER_CAPACITY)
        if load_data:
            gd = GameDataService(session)
            counts = await gd.load_all()
            log.info("initdb.game_data.loaded", **counts)
        await session.commit()

    log.info("initdb.complete")


# ---------------------------------------------------------------------------
# Component runners
# ---------------------------------------------------------------------------

async def run_api(host: str, port: int, reload: bool = False) -> None:
    """Run the FastAPI app via :class:`uvicorn.Server` (non-blocking)."""
    import uvicorn

    config = uvicorn.Config(
        "nationcraft.api.app:create_app",
        factory=True,
        host=host,
        port=port,
        reload=reload,
        workers=1,  # single-process when embedded
        log_config=None,
        access_log=False,  # we have our own RequestIdMiddleware
    )
    server = uvicorn.Server(config)
    log.info("api.starting", host=host, port=port, reload=reload)
    await server.serve()


async def run_worker() -> None:
    """Run the tick engine worker.

    Plugin loading is **idempotent** (see ``PluginRegistry.add``): if the
    API lifespan has already loaded plugins (which happens when running
    all-in-one with ``python main.py``), this is a no-op. If the worker is
    run standalone (``python main.py --only worker``), this is the only
    place plugins are loaded — without this, plugin tick hooks would
    never fire in worker-only mode.

    Previously, even with idempotent registry, this function's
    ``loader.discover() + loader.load_all()`` calls in addition to the
    API lifespan doing the same caused the space_race plugin's tick hooks
    to be subscribed TWICE per tick (because the old ``PluginRegistry.add``
    unconditionally overwrote the existing record, resetting its state
    from ENABLED back to DISCOVERED). The idempotent ``add`` + the
    idempotent ``HookRegistry.register`` together eliminate the duplicate
    subscription.
    """
    from nationcraft.application.services import register_default_handlers
    from nationcraft.core.plugins import PluginLoader
    from nationcraft.core.tick import TickRunner

    if settings.PLUGINS_ENABLED:
        loader = PluginLoader(settings.plugins_dirs_list)
        loader.discover()
        loader.load_all()

    register_default_handlers()
    log.info("worker.starting", interval=settings.TICK_INTERVAL_SECONDS)
    runner = TickRunner()
    await runner.run()


async def run_bot(use_webhook: bool = False) -> None:
    """Run the aiogram Telegram bot."""
    if not settings.TELEGRAM_BOT_TOKEN:
        log.warning("bot.skipped", reason="TELEGRAM_BOT_TOKEN not set")
        return
    from nationcraft.bot.app import run_bot
    log.info("bot.starting", webhook=use_webhook)
    await run_bot(use_webhook=use_webhook)


# ---------------------------------------------------------------------------
# Combined runner
# ---------------------------------------------------------------------------

async def run_all(host: str, port: int, use_webhook: bool = False) -> None:
    """Run API + worker + bot concurrently in one event loop."""
    tasks: list[asyncio.Task] = [
        asyncio.create_task(run_api(host, port), name="api"),
        asyncio.create_task(run_worker(), name="worker"),
    ]
    if settings.TELEGRAM_BOT_TOKEN:
        tasks.append(asyncio.create_task(run_bot(use_webhook=use_webhook), name="bot"))
    else:
        log.warning("bot.skipped", reason="TELEGRAM_BOT_TOKEN not set")

    # Graceful shutdown via SIGINT / SIGTERM.
    stop_event = asyncio.Event()

    def _signal_handler(*_: object) -> None:
        log.info("main.signal.received")
        stop_event.set()

    loop = asyncio.get_event_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _signal_handler)
        except (NotImplementedError, RuntimeError):
            # Windows doesn't support add_signal_handler; SIGINT is
            # still raised as KeyboardInterrupt via the default handler.
            pass

    # Wait for either a task to fail or a signal to fire.
    watcher = asyncio.create_task(stop_event.wait(), name="stop_watcher")
    done, pending = await asyncio.wait(
        tasks + [watcher],
        return_when=asyncio.FIRST_COMPLETED,
    )

    # If a real task finished first (error or unexpected exit), log it.
    for t in done:
        if t is watcher:
            continue
        exc = t.exception()
        if exc:
            log.error("main.task.exited", name=t.get_name(), error=str(exc))
        else:
            log.warning("main.task.exited", name=t.get_name())

    # Cancel everything still running.
    for t in pending:
        t.cancel()
    await asyncio.gather(*pending, return_exceptions=True)
    log.info("main.stopped")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="nationcraft",
        description="NationCraft launcher — run the API, worker, and bot in one process.",
    )
    parser.add_argument(
        "--only",
        choices=["api", "worker", "bot"],
        help="Run only one component (default: run all three).",
    )
    parser.add_argument("--host", default=settings.API_HOST, help=f"API bind host (default: {settings.API_HOST})")
    parser.add_argument("--port", type=int, default=settings.API_PORT, help=f"API bind port (default: {settings.API_PORT})")
    parser.add_argument("--reload", action="store_true", help="Enable auto-reload (API only, dev mode).")
    parser.add_argument("--webhook", action="store_true", help="Run bot in webhook mode.")
    parser.add_argument("--migrate", action="store_true", help="Run Alembic migrations to head, then continue starting.")
    parser.add_argument(
        "--initdb",
        action="store_true",
        help="Migrate + seed worlds + load game data, then exit. Does NOT start servers.",
    )
    parser.add_argument(
        "--local",
        action="store_true",
        help="Force local-dev mode: SQLite DB, localhost Redis, localhost API URL. "
             "Overrides DATABASE_URL, REDIS_URL, and API_BASE_URL.",
    )
    parser.add_argument(
        "--log-level",
        default=settings.LOG_LEVEL,
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        help=f"Log level (default: {settings.LOG_LEVEL}).",
    )
    parser.add_argument(
        "--log-format",
        default=settings.LOG_FORMAT,
        choices=["json", "console"],
        help=f"Log format (default: {settings.LOG_FORMAT}).",
    )
    return parser.parse_args(argv)


# Hostnames that only resolve inside a Docker Compose network.
_DOCKER_HOSTNAMES = {"postgres", "redis", "api", "db"}


def _extract_hostname(url: str) -> str | None:
    """Extract the hostname from a URL like ``redis://redis:6379/0`` or ``postgresql+asyncpg://user:pw@host:5432/db``."""
    m = re.search(r"@([^:/@]+)", url) or re.search(r"//([^:/@]+)", url)
    return m.group(1) if m else None


def _apply_local_overrides() -> None:
    """Force local-dev config: SQLite + localhost Redis + localhost API URL."""
    os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///nationcraft.db"
    os.environ["REDIS_URL"] = "redis://localhost:6379/0"
    os.environ["API_BASE_URL"] = "http://localhost:8000"
    # Reload settings so they pick up the new env values.
    from nationcraft.core.config import settings as _settings, Settings
    new = Settings()
    # Mutate the singleton in place so all callers see the new values.
    # Use type(new).model_fields (class attribute) to avoid the
    # PydanticDeprecatedSince211 warning about instance attribute access.
    for field in type(new).model_fields:
        setattr(_settings, field, getattr(new, field))
    log.info(
        "main.config.local_overrides_applied",
        database_url=_settings.DATABASE_URL,
        redis_url=_settings.REDIS_URL,
        api_base_url=_settings.API_BASE_URL,
    )


def _validate_config() -> int:
    """Sanity-check critical settings before starting. Returns 0 if OK, 1 if fatal."""
    url = settings.DATABASE_URL
    if not url or "://" not in url:
        log.error(
            "main.config.invalid_database_url",
            url=url,
            hint="Set DATABASE_URL in your .env file. Examples:\n"
                 "  - SQLite (local dev): DATABASE_URL=sqlite+aiosqlite:///nationcraft.db\n"
                 "  - PostgreSQL (prod):  DATABASE_URL=postgresql+asyncpg://user:pass@host:5432/db",
        )
        return 1
    if not settings.SECRET_KEY or settings.SECRET_KEY.startswith("change-me"):
        log.warning(
            "main.config.insecure_secret_key",
            hint="Set SECRET_KEY to a 32-byte random hex string. "
                 "Generate one with: python -c \"import secrets; print(secrets.token_hex(32))\"",
        )

    # Warn about Docker-only hostnames when running locally (not in Docker).
    in_docker = Path("/.dockerenv").exists() or os.environ.get("KUBERNETES_SERVICE_HOST") is not None
    if not in_docker:
        for label, url in [("DATABASE_URL", settings.DATABASE_URL),
                           ("REDIS_URL", settings.REDIS_URL),
                           ("API_BASE_URL", settings.API_BASE_URL)]:
            host = _extract_hostname(url or "")
            if host and host in _DOCKER_HOSTNAMES:
                log.error(
                    "main.config.docker_hostname_outside_docker",
                    setting=label,
                    hostname=host,
                    url=url,
                    hint=(
                        f"{label}={url} references the Docker hostname '{host}', "
                        f"but you're running outside Docker. Either:\n"
                        f"  1. Run `python main.py --local` to auto-use SQLite + localhost, OR\n"
                        f"  2. Edit .env to use 'localhost' instead of '{host}', OR\n"
                        f"  3. Run via `docker-compose up -d --build` to use the Docker network."
                    ),
                )
                return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    # --local: apply overrides BEFORE configuring logging so the log shows them.
    if args.local:
        _apply_local_overrides()

    configure_logging(args.log_level, args.log_format)
    log.info(
        "main.start",
        only=args.only,
        host=args.host,
        port=args.port,
        env=settings.ENV,
        local=args.local,
    )

    # Validate config before doing anything destructive.
    if (rc := _validate_config()) != 0:
        return rc

    # --initdb: migrate + seed + exit (no servers started).
    if args.initdb:
        try:
            asyncio.run(initdb(load_data=True))
            return 0
        except Exception as exc:  # noqa: BLE001
            log.exception("main.initdb.failed", error=str(exc))
            return 1

    # --migrate: run migrations, then continue.
    # Migrations run synchronously before any async work for the same
    # reason as --initdb (alembic env.py uses asyncio.run internally).
    if args.migrate:
        try:
            run_migrations()
        except Exception as exc:  # noqa: BLE001
            log.exception("main.migrate.failed", error=str(exc))
            return 1

    try:
        if args.only == "api":
            asyncio.run(run_api(args.host, args.port, reload=args.reload))
        elif args.only == "worker":
            asyncio.run(run_worker())
        elif args.only == "bot":
            asyncio.run(run_bot(use_webhook=args.webhook))
        else:
            asyncio.run(run_all(args.host, args.port, use_webhook=args.webhook))
    except KeyboardInterrupt:
        log.info("main.interrupted")
    except Exception as exc:  # noqa: BLE001
        log.exception("main.fatal", error=str(exc))
        return 1
    finally:
        log.info("main.exit")
    return 0


if __name__ == "__main__":
    sys.exit(main())
