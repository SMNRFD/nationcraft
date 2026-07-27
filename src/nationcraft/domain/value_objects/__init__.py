"""Domain value objects (immutable, side-effect free)."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class ResourceAmount:
    """An amount of a resource identified by ``key``."""

    key: str
    amount: float

    def __post_init__(self) -> None:
        if not self.key:
            raise ValueError("ResourceAmount.key required")
        if self.amount < 0:
            raise ValueError("ResourceAmount.amount must be non-negative")

    def add(self, other: "ResourceAmount") -> "ResourceAmount":
        if other.key != self.key:
            raise ValueError("Cannot add different resources")
        return ResourceAmount(self.key, self.amount + other.amount)

    def subtract(self, other: "ResourceAmount") -> "ResourceAmount":
        if other.key != self.key:
            raise ValueError("Cannot subtract different resources")
        return ResourceAmount(self.key, max(0.0, self.amount - other.amount))


@dataclass(frozen=True, slots=True)
class ResourcePack:
    """A bundle of resources keyed by resource key."""

    amounts: dict[str, float]

    @classmethod
    def empty(cls) -> "ResourcePack":
        return cls({})

    @classmethod
    def of(cls, **amounts: float) -> "ResourcePack":
        return cls({k: float(v) for k, v in amounts.items() if v})

    def __add__(self, other: "ResourcePack") -> "ResourcePack":
        out = dict(self.amounts)
        for k, v in other.amounts.items():
            out[k] = out.get(k, 0.0) + v
        return ResourcePack(out)

    def __sub__(self, other: "ResourcePack") -> "ResourcePack":
        out = dict(self.amounts)
        for k, v in other.amounts.items():
            out[k] = max(0.0, out.get(k, 0.0) - v)
        return ResourcePack(out)

    def __contains__(self, key: str) -> bool:
        return self.amounts.get(key, 0.0) > 0

    def covers(self, other: "ResourcePack") -> bool:
        return all(self.amounts.get(k, 0.0) >= v for k, v in other.amounts.items())

    def get(self, key: str) -> float:
        return self.amounts.get(key, 0.0)


@dataclass(frozen=True, slots=True)
class Coordinates:
    x: int
    y: int


@dataclass(frozen=True, slots=True)
class CombatModifiers:
    attack_multiplier: float = 1.0
    defense_multiplier: float = 1.0
    terrain_bonus: float = 0.0
    tech_bonus: float = 0.0
    morale: float = 1.0


@dataclass(frozen=True, slots=True)
class MissionObjective:
    """Evaluates whether a mission's goal has been achieved."""

    type: str
    params: dict[str, Any]

    def evaluate(self, ctx: dict[str, Any]) -> bool:
        """Evaluate against a context dict provided by the mission service."""
        op = self.type
        target = self.params.get("target")
        current = ctx.get(self.params.get("metric", ""))
        if current is None:
            return False
        if op == ">=":
            return current >= target
        if op == "<=":
            return current <= target
        if op == "==":
            return current == target
        if op == ">":
            return current > target
        if op == "<":
            return current < target
        return False
