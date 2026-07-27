"""Tick runner — scheduling wrapper that ticks all worlds every N seconds."""
from __future__ import annotations

import asyncio
import time

from nationcraft.core.config import settings
from nationcraft.core.events import Event, event_bus
from nationcraft.core.logging import get_logger
from nationcraft.core.tick.engine import TickContext, tick_engine

log = get_logger(__name__)


class TickRunner:
    """Async scheduler that fires ticks across all worlds."""

    def __init__(self, interval: int | None = None) -> None:
        self.interval = interval or settings.TICK_INTERVAL_SECONDS
        self._stop = asyncio.Event()
        self._tasks: list[asyncio.Task] = []

    async def run(self) -> None:
        from nationcraft.application.services.world_service import WorldService
        from nationcraft.infrastructure.db.session import AsyncSessionLocal

        log.info("tick.runner.start", interval=self.interval)
        while not self._stop.is_set():
            try:
                async with AsyncSessionLocal() as session:
                    ws = WorldService(session)
                    worlds = await ws.list_all_active()
                    for world in worlds:
                        ctx = TickContext(world_id=world.id, tick=world.tick_count + 1)
                        await tick_engine.run(ctx)
                    await ws.increment_ticks([w.id for w in worlds])
                    await session.commit()
            except Exception:  # noqa: BLE001
                log.exception("tick.runner.error")
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=self.interval)
            except asyncio.TimeoutError:
                pass

        log.info("tick.runner.stop")

    def stop(self) -> None:
        self._stop.set()


async def run_worker() -> None:
    """Entry point used by the ``nationcraft worker`` CLI."""
    runner = TickRunner()
    loop = asyncio.get_running_loop()
    for sig in ("SIGINT", "SIGTERM"):
        try:
            loop.add_signal_handler(getattr(__import__("signal"), sig), runner.stop)
        except NotImplementedError:
            pass
    await runner.run()
