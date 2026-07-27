"""Tick runner — scheduling wrapper that ticks all worlds every N seconds."""
from __future__ import annotations

import asyncio
import time

from nationcraft.core.config import settings
from nationcraft.core.logging import get_logger
from nationcraft.core.tick.engine import TickContext, tick_engine

log = get_logger(__name__)


class TickRunner:
    """Async scheduler that fires ticks across all worlds.

    When the database is unreachable, the runner logs a clear, concise
    error (not a full traceback) every tick and keeps trying — it never
    crashes. This lets the rest of the system (API, bot) continue to
    function while the DB is being restored.
    """

    def __init__(self, interval: int | None = None) -> None:
        self.interval = interval or settings.TICK_INTERVAL_SECONDS
        self._stop = asyncio.Event()
        self._tasks: list[asyncio.Task] = []
        self._consecutive_errors = 0
        self._last_error_logged = 0.0

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
                # Reset error counter on success.
                if self._consecutive_errors:
                    log.info(
                        "tick.runner.recovered",
                        previous_errors=self._consecutive_errors,
                    )
                    self._consecutive_errors = 0
            except Exception as exc:  # noqa: BLE001
                self._consecutive_errors += 1
                # Throttle error logging: log every tick for the first 3,
                # then at most once per 5 minutes.
                now = time.time()
                should_log = (
                    self._consecutive_errors <= 3
                    or now - self._last_error_logged > 300
                )
                if should_log:
                    self._last_error_logged = now
                    # Extract a short error message instead of dumping the full traceback.
                    msg = str(exc).split("\n")[0][:200]
                    log.error(
                        "tick.runner.error",
                        error=msg,
                        consecutive_errors=self._consecutive_errors,
                        hint=(
                            "The tick engine cannot reach the database. "
                            "Check that DATABASE_URL is correct and the DB is running."
                        ) if self._consecutive_errors == 1 else None,
                    )
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
