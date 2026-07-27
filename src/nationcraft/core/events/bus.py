"""In-process async event bus with prioritized handlers, error isolation, and hooks for plugins."""
from __future__ import annotations

import asyncio
import inspect
from collections import defaultdict
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Awaitable, Callable

from nationcraft.core.logging import get_logger

log = get_logger(__name__)

EventHandler = Callable[["Event"], Any | Awaitable[Any]]


class EventPriority(StrEnum):
    LOWEST = "lowest"
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    HIGHEST = "highest"
    MONITOR = "monitor"  # Observers only; cannot mutate state.


_PRIORITY_ORDER = {
    EventPriority.HIGHEST: 0,
    EventPriority.HIGH: 1,
    EventPriority.NORMAL: 2,
    EventPriority.LOW: 3,
    EventPriority.LOWEST: 4,
    EventPriority.MONITOR: 5,
}


@dataclass(frozen=True, slots=True)
class Event:
    """Base event. Subclass to define specific events."""

    type: str
    payload: dict[str, Any] = field(default_factory=dict)
    world_id: int | None = None
    player_id: int | None = None

    def __post_init__(self) -> None:
        if not self.type:
            raise ValueError("Event.type must be non-empty")


@dataclass(slots=True)
class _Subscription:
    handler: EventHandler
    priority: EventPriority
    once: bool = False


class EventBus:
    """Async event bus.

    Features:
    * Subscriptions with priority ordering.
    * ``once`` subscriptions auto-unsubscribe after first fire.
    * Handlers can be sync or async.
    * Errors in one handler do not block others.
    * Optional hook injection point for plugins/extensions.
    """

    def __init__(self) -> None:
        self._subs: dict[str, list[_Subscription]] = defaultdict(list)
        self._wildcard: list[_Subscription] = []
        self._lock = asyncio.Lock()

    def subscribe(
        self,
        event_type: str | None,
        handler: EventHandler,
        *,
        priority: EventPriority = EventPriority.NORMAL,
        once: bool = False,
    ) -> Callable[[], None]:
        """Register a handler. ``event_type=None`` means wildcard.

        Returns an unsubscribe callable.
        """
        sub = _Subscription(handler=handler, priority=priority, once=once)
        if event_type is None:
            self._wildcard.append(sub)
            bucket = self._wildcard
        else:
            self._subs[event_type].append(sub)
            bucket = self._subs[event_type]
        bucket.sort(key=lambda s: _PRIORITY_ORDER[s.priority])

        def _unsubscribe() -> None:
            try:
                bucket.remove(sub)
            except ValueError:
                pass

        return _unsubscribe

    async def publish(self, event: Event) -> None:
        """Publish an event to all matching subscribers."""
        targets = list(self._subs.get(event.type, ())) + list(self._wildcard)
        if not targets:
            return
        log.debug("event.publish", event_type=event.type, payload=event.payload)

        for sub in targets:
            await self._invoke(sub, event)
            if sub.once:
                try:
                    bucket = self._wildcard if sub in self._wildcard else self._subs.get(event.type, [])
                    bucket.remove(sub)
                except ValueError:
                    pass

    async def _invoke(self, sub: _Subscription, event: Event) -> None:
        try:
            result = sub.handler(event)
            if inspect.isawaitable(result):
                await result
        except Exception:  # noqa: BLE001
            log.exception(
                "event.handler.failed",
                event_type=event.type,
                handler=getattr(sub.handler, "__qualname__", str(sub.handler)),
            )


# Singleton bus used by the entire application.
event_bus = EventBus()


def emit(event_type: str, payload: dict[str, Any] | None = None, **kwargs: Any) -> asyncio.Task[None]:
    """Convenience fire-and-forget publisher returning the asyncio Task."""
    return asyncio.create_task(event_bus.publish(Event(type=event_type, payload=payload or {}, **kwargs)))
