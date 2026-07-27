"""Unit tests for the extension hook system."""
from __future__ import annotations

import pytest

from nationcraft.core.extensions import HookPriority, HookRegistry, hook


@pytest.mark.asyncio
async def test_chain_default_only() -> None:
    reg = HookRegistry()
    result = await reg.invoke("calc.x", default=42)
    assert result == 42


@pytest.mark.asyncio
async def test_chain_overrides() -> None:
    reg = HookRegistry()
    reg._hooks.clear()  # ensure fresh state
    reg.register("calc.x", lambda v: v + 1, priority=HookPriority.LOW)
    reg.register("calc.x", lambda v: v * 10, priority=HookPriority.HIGH)
    result = await reg.invoke("calc.x", default=1)
    # HIGH runs first (1*10=10), then LOW (10+1=11).
    assert result == 11


@pytest.mark.asyncio
async def test_async_handler() -> None:
    reg = HookRegistry()
    reg._hooks.clear()

    async def async_handler(v: int) -> int:
        return v + 100

    reg.register("calc.y", async_handler)
    result = await reg.invoke("calc.y", default=0)
    assert result == 100


@pytest.mark.asyncio
async def test_clear_plugin() -> None:
    reg = HookRegistry()
    reg._hooks.clear()
    reg.register("calc.z", lambda v: v + 1, plugin_id="p1")
    reg.register("calc.z", lambda v: v + 2, plugin_id="p2")
    reg.clear_plugin("p1")
    result = await reg.invoke("calc.z", default=0)
    assert result == 2
