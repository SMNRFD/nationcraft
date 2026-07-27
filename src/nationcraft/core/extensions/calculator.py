"""Calculator chain helpers for formula-driven systems (production, combat, etc.)."""
from __future__ import annotations

from typing import Any, Awaitable, Callable

from .hooks import HookRegistry


class Calculator:
    """Convenience wrapper around a named hook for formula calculations."""

    __slots__ = ("name", "default_fn")

    def __init__(self, name: str, default_fn: Callable[..., Any]) -> None:
        self.name = name
        self.default_fn = default_fn

    async def compute(self, *args: Any, **kwargs: Any) -> Any:
        default = self.default_fn(*args, **kwargs)
        if inspect_awaitable(default):
            default = await default  # type: ignore[assignment]
        return await HookRegistry.instance().invoke(self.name, default, *args, **kwargs)


def inspect_awaitable(x: Any) -> bool:
    import inspect
    return inspect.isawaitable(x)


class CalculatorChain:
    """Group of calculators sharing a registry (for DI/testing)."""

    def __init__(self) -> None:
        self._calcs: dict[str, Calculator] = {}

    def register(self, calc: Calculator) -> None:
        self._calcs[calc.name] = calc

    def get(self, name: str) -> Calculator:
        return self._calcs[name]

    def compute(self, name: str, *args: Any, **kwargs: Any) -> Awaitable[Any]:
        return self._calcs[name].compute(*args, **kwargs)
