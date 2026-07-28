"""Tick engine — orchestrates per-tick processing phases.

Each tick the engine walks every world through the phases defined in
:class:`TickPhases`. Each phase is a registered async callable. Plugins
can register their own phase handlers via the hook
``tick.phase.<phase_name>``.
"""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

from nationcraft.core.config import TickPhases
from nationcraft.core.events import Event, event_bus
from nationcraft.core.extensions import HookRegistry
from nationcraft.core.logging import get_logger

log = get_logger(__name__)

PhaseHandler = Callable[["TickContext"], Awaitable[Any] | Any]


@dataclass(slots=True)
class TickContext:
    """Mutable per-tick, per-world context passed to every phase."""

    world_id: int
    tick: int
    started_at: float = field(default_factory=time.time)
    metrics: dict[str, Any] = field(default_factory=dict)
    skip_remaining: bool = False


class TickEngine:
    """Holds the ordered list of phase handlers and runs them per tick."""

    def __init__(self) -> None:
        self._handlers: dict[TickPhases, list[tuple[str, PhaseHandler]]] = {}

    def register(self, phase: TickPhases, name: str, handler: PhaseHandler) -> None:
        self._handlers.setdefault(phase, []).append((name, handler))

    def unregister(self, phase: TickPhases, name: str) -> None:
        if phase in self._handlers:
            self._handlers[phase] = [(n, h) for n, h in self._handlers[phase] if n != name]

    async def run(self, ctx: TickContext) -> None:
        await event_bus.publish(Event(
            type="tick.started",
            world_id=ctx.world_id,
            payload={"tick": ctx.tick},
        ))
        for phase in TickPhases:
            if ctx.skip_remaining:
                break
            await self._run_phase(phase, ctx)
            # Yield control to the event loop between phases so the API
            # and bot can process requests during long ticks.
            await asyncio.sleep(0)
        await event_bus.publish(Event(
            type="tick.finished",
            world_id=ctx.world_id,
            payload={"tick": ctx.tick, "duration_ms": (time.time() - ctx.started_at) * 1000},
        ))

    async def _run_phase(self, phase: TickPhases, ctx: TickContext) -> None:
        # Built-in handlers
        for name, handler in self._handlers.get(phase, ()):
            try:
                result = handler(ctx)
                if result is not None and hasattr(result, "__await__"):
                    await result
            except Exception:  # noqa: BLE001
                log.exception("tick.phase.failed", phase=phase.value, handler=name, world_id=ctx.world_id)

        # Plugin-provided handlers via hook
        try:
            await HookRegistry.instance().invoke(
                f"tick.phase.{phase.value}", None, ctx
            )
        except Exception:  # noqa: BLE001
            log.exception("tick.phase.hook.failed", phase=phase.value, world_id=ctx.world_id)


# Singleton
tick_engine = TickEngine()
