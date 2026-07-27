"""Application entry points: API server, Telegram bot, tick worker, migrate, admin tools."""
from __future__ import annotations

import asyncio
import logging
import signal
import sys
from typing import Any

import click

from nationcraft.core.config import settings
from nationcraft.core.logging import configure_logging

log = logging.getLogger(__name__)


@click.group(invoke_without_command=True)
@click.option("--version", is_flag=True, help="Show version and exit.")
def main(version: bool) -> None:
    """NationCraft command-line launcher."""
    if version:
        from nationcraft import __version__
        click.echo(f"nationcraft {__version__}")
        sys.exit(0)


@main.command()
@click.option("--host", default=None, help="Bind host (defaults to API_HOST).")
@click.option("--port", type=int, default=None, help="Bind port (defaults to API_PORT).")
@click.option("--reload", is_flag=True, help="Enable auto-reload (dev only).")
def api(host: str | None, port: int | None, reload: bool) -> None:
    """Run the FastAPI REST API server."""
    configure_logging(settings.LOG_LEVEL, settings.LOG_FORMAT)
    import uvicorn

    uvicorn.run(
        "nationcraft.api.app:create_app",
        factory=True,
        host=host or settings.API_HOST,
        port=port or settings.API_PORT,
        reload=reload,
        workers=settings.API_WORKERS if not reload else 1,
        log_config=None,
    )


@main.command()
@click.option("--webhook", is_flag=True, help="Run in webhook mode (otherwise long polling).")
def bot(webhook: bool) -> None:
    """Run the aiogram Telegram bot."""
    configure_logging(settings.LOG_LEVEL, settings.LOG_FORMAT)
    from nationcraft.bot.app import run_bot
    asyncio.run(run_bot(use_webhook=webhook))


@main.command()
def worker() -> None:
    """Run the tick engine worker (game loop)."""
    configure_logging(settings.LOG_LEVEL, settings.LOG_FORMAT)
    from nationcraft.workers.tick_worker import run_worker
    asyncio.run(run_worker())


@main.command()
@click.option("--revision", default="head", help="Target alembic revision.")
def migrate(revision: str) -> None:
    """Apply database migrations."""
    configure_logging(settings.LOG_LEVEL, settings.LOG_FORMAT)
    from alembic.config import Config
    from alembic import command
    cfg = Config("alembic.ini")
    command.upgrade(cfg, revision)
    click.echo(f"Migrated to {revision}")


@main.command()
@click.option("--auto", "-a", is_flag=True, help="Generate without prompts.")
@click.option("--message", "-m", default="auto", help="Revision message.")
def makemigrations(auto: bool, message: str) -> None:
    """Autogenerate a new Alembic migration."""
    configure_logging(settings.LOG_LEVEL, settings.LOG_FORMAT)
    from alembic.config import Config
    from alembic import command
    cfg = Config("alembic.ini")
    command.revision(cfg, message=message, autogenerate=True)
    click.echo("Migration generated.")


@main.command()
@click.option("--worlds", is_flag=True, help="Initialize default worlds.")
@click.option("--data", is_flag=True, help="Load game data YAML into DB.")
def initdb(worlds: bool, data: bool) -> None:
    """Initialize database: run migrations, seed worlds, load game data."""
    configure_logging(settings.LOG_LEVEL, settings.LOG_FORMAT)

    async def _run() -> None:
        from nationcraft.infrastructure.db.session import engine
        from alembic.config import Config
        from alembic import command
        cfg = Config("alembic.ini")
        command.upgrade(cfg, "head")
        from nationcraft.application.services.world_service import WorldService
        from nationcraft.infrastructure.db.session import AsyncSessionLocal
        async with AsyncSessionLocal() as session:
            ws = WorldService(session)
            await ws.ensure_worlds(capacity=settings.WORLD_PLAYER_CAPACITY)
            if data:
                from nationcraft.application.services.game_data_service import GameDataService
                gd = GameDataService(session)
                await gd.load_all()
        await engine.dispose()
        click.echo("Database initialized.")

    asyncio.run(_run())


@main.command()
@click.argument("action", type=click.Choice(["enable", "disable", "list", "info"]))
@click.argument("plugin_name", required=False)
def plugin(action: str, plugin_name: str | None) -> None:
    """Manage plugins."""
    configure_logging(settings.LOG_LEVEL, settings.LOG_FORMAT)
    click.echo(f"plugin {action} {plugin_name or ''}")


if __name__ == "__main__":
    main()
