"""Unit tests for the event bus."""
from __future__ import annotations

import asyncio

import pytest

from nationcraft.core.events import Event, EventBus, EventPriority


@pytest.mark.asyncio
async def test_subscribe_and_publish() -> None:
    bus = EventBus()
    received: list[Event] = []

    async def handler(e: Event) -> None:
        received.append(e)

    bus.subscribe("test.event", handler)
    await bus.publish(Event(type="test.event", payload={"x": 1}))
    assert len(received) == 1
    assert received[0].payload["x"] == 1


@pytest.mark.asyncio
async def test_priority_order() -> None:
    bus = EventBus()
    order: list[str] = []

    async def h1(e: Event) -> None:
        order.append("h1")

    async def h2(e: Event) -> None:
        order.append("h2")

    async def h3(e: Event) -> None:
        order.append("h3")

    bus.subscribe("e", h1, priority=EventPriority.LOW)
    bus.subscribe("e", h2, priority=EventPriority.HIGHEST)
    bus.subscribe("e", h3, priority=EventPriority.NORMAL)
    await bus.publish(Event(type="e"))
    assert order == ["h2", "h3", "h1"]


@pytest.mark.asyncio
async def test_wildcard_subscriber() -> None:
    bus = EventBus()
    seen: list[str] = []

    async def watcher(e: Event) -> None:
        seen.append(e.type)

    bus.subscribe(None, watcher, priority=EventPriority.MONITOR)
    await bus.publish(Event(type="a.b"))
    await bus.publish(Event(type="c.d"))
    assert seen == ["a.b", "c.d"]


@pytest.mark.asyncio
async def test_handler_error_does_not_block_others() -> None:
    bus = EventBus()
    reached: list[str] = []

    async def bad(e: Event) -> None:
        raise RuntimeError("boom")

    async def good(e: Event) -> None:
        reached.append("good")

    bus.subscribe("e", bad, priority=EventPriority.HIGH)
    bus.subscribe("e", good, priority=EventPriority.LOW)
    await bus.publish(Event(type="e"))
    assert reached == ["good"]
