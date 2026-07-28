"""Tick worker entrypoint — used by the ``nationcraft worker`` CLI command."""
from __future__ import annotations

from nationcraft.application.services import register_default_handlers
from nationcraft.core.logging import get_logger
from nationcraft.core.tick import TickRunner

log = get_logger(__name__)


async def run_worker() -> None:
    """Initialize handlers and start the tick runner.

    NOTE: Plugins are loaded by the API lifespan, NOT here. When
    running ``python main.py`` (all-in-one), the API lifespan loads
    plugins once. Loading them again here would double-register hooks
    and cause duplicate tick execution.
    """
    register_default_handlers()
    log.info("worker.start")
    runner = TickRunner()
    await runner.run()
