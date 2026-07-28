"""Hook registry.

Hooks are well-known extension points (e.g. ``economy.production_rate``,
``combat.attack_damage``). Extensions register callable handlers for a
hook name; the calculator chain runs them in priority order.

Unlike the event bus, hooks **return values** and can short-circuit the
chain (an extension can completely override a calculation).
"""
from __future__ import annotations

import inspect
from dataclasses import dataclass
from enum import IntEnum
from typing import Any, Awaitable, Callable

from nationcraft.core.logging import get_logger

log = get_logger(__name__)


class HookPriority(IntEnum):
    HIGHEST = 0
    HIGH = 100
    DEFAULT = 500
    LOW = 900
    LOWEST = 1000


HookHandler = Callable[..., Any | Awaitable[Any]]


@dataclass(slots=True)
class Hook:
    name: str
    handler: HookHandler
    priority: int = HookPriority.DEFAULT
    plugin_id: str | None = None


def hook(name: str, *, priority: int = HookPriority.DEFAULT) -> Callable[[HookHandler], HookHandler]:
    """Decorator to register a function as a hook handler on import."""

    def _wrap(fn: HookHandler) -> HookHandler:
        HookRegistry.instance().register(name, fn, priority=priority)
        return fn

    return _wrap


def extension(name: str | None = None) -> Callable[[type], type]:
    """Class decorator marking an extension. Optional metadata only."""

    def _wrap(cls: type) -> type:
        cls.__extension_name__ = name or cls.__name__  # type: ignore[attr-defined]
        return cls

    return _wrap


class HookRegistry:
    """Process-wide registry of hook handlers."""

    _instance: "HookRegistry | None" = None

    @classmethod
    def instance(cls) -> "HookRegistry":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def __init__(self) -> None:
        self._hooks: dict[str, list[Hook]] = {}

    def register(self, name: str, handler: HookHandler, *, priority: int = HookPriority.DEFAULT, plugin_id: str | None = None) -> None:
        """Idempotent on (name, handler) — registering the same callable
        twice for the same hook is a no-op. This protects against plugins
        being loaded twice (which used to double every hook invocation and
        double the work done per tick on SQLite, worsening lock contention).
        """
        bucket = self._hooks.setdefault(name, [])
        # Skip if this exact handler is already registered for this hook.
        for existing in bucket:
            if existing.handler is handler:
                return
        bucket.append(
            Hook(name=name, handler=handler, priority=priority, plugin_id=plugin_id)
        )
        bucket.sort(key=lambda h: h.priority)

    def unregister(self, name: str, handler: HookHandler) -> None:
        if name in self._hooks:
            self._hooks[name] = [h for h in self._hooks[name] if h.handler != handler]

    def clear_plugin(self, plugin_id: str) -> None:
        for name in list(self._hooks.keys()):
            self._hooks[name] = [h for h in self._hooks[name] if h.plugin_id != plugin_id]
            if not self._hooks[name]:
                del self._hooks[name]

    def handlers(self, name: str) -> list[Hook]:
        return list(self._hooks.get(name, []))

    def has_handlers(self, name: str) -> bool:
        return bool(self._hooks.get(name))

    async def invoke(self, name: str, default: Any, *args: Any, **kwargs: Any) -> Any:
        """Invoke all handlers for a hook in priority order.

        Each handler receives the previous result as the first positional
        argument (chaining). The first handler receives ``default``.
        """
        result = default
        for h in self.handlers(name):
            try:
                out = h.handler(result, *args, **kwargs)
                if inspect.isawaitable(out):
                    out = await out
                result = out
            except Exception:  # noqa: BLE001
                log.exception("hook.failed", hook=name, plugin=h.plugin_id)
        return result
