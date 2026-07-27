"""Tick worker entrypoint — used by the ``nationcraft worker`` CLI command."""
from __future__ import annotations

from nationcraft.application.services import register_default_handlers
from nationcraft.core.logging import get_logger
from nationcraft.core.tick import TickRunner

log = get_logger(__name__)


async def run_worker() -> None:
    """Initialize handlers and start the tick runner."""
    # Discover and load plugins so their tick hooks are registered.
    from nationcraft.core.config import settings
    if settings.PLUGINS_ENABLED:
        from nationcraft.core.plugins import PluginLoader
        loader = PluginLoader(settings.plugins_dirs_list)
        loader.discover()
        loader.load_all()
    # Register default built-in tick handlers.
    register_default_handlers()
    log.info("worker.start")
    runner = TickRunner()
    await runner.run()
