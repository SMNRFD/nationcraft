"""Unit tests for the resource pack value object."""
from __future__ import annotations

import pytest

from nationcraft.domain.value_objects import ResourceAmount, ResourcePack


def test_resource_amount_add() -> None:
    a = ResourceAmount("food", 10)
    b = ResourceAmount("food", 5)
    assert a.add(b).amount == 15


def test_resource_amount_subtract_clamps_to_zero() -> None:
    a = ResourceAmount("food", 3)
    b = ResourceAmount("food", 10)
    assert a.subtract(b).amount == 0


def test_resource_pack_covers() -> None:
    pack = ResourcePack.of(food=100, water=50)
    assert pack.covers(ResourcePack.of(food=50, water=10))
    assert not pack.covers(ResourcePack.of(food=200))


def test_resource_pack_add_subtract() -> None:
    p = ResourcePack.of(food=100)
    p = p + ResourcePack.of(food=50, water=10)
    assert p.get("food") == 150
    assert p.get("water") == 10
    p = p - ResourcePack.of(food=200)  # clamps to 0
    assert p.get("food") == 0
    assert p.get("water") == 10  # untouched


def test_resource_amount_rejects_negative() -> None:
    with pytest.raises(ValueError):
        ResourceAmount("food", -1)
