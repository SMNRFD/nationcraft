"""Domain entity definitions.

These are abstract entities (Protocol-style) describing the shape of
aggregate roots used by services. They intentionally have no ORM
decorators so the domain stays persistence-agnostic. Concrete ORM models
live in ``nationcraft.infrastructure.db.models`` and implement these
shapes.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol

from nationcraft.domain.enums import (
    AllianceRole,
    BuildingStatus,
    DiplomaticStatus,
    EventCategory,
    GovernmentType,
    MarketOrderSide,
    MarketOrderStatus,
    MissionCategory,
    MissionStatus,
    NotificationLevel,
    OrderType,
    PlayerRole,
    ResearchStatus,
    UnitState,
    WarStatus,
    WarType,
    WorldStatus,
)


@dataclass(slots=True)
class World:
    id: int
    name: str
    slug: str
    status: WorldStatus
    player_capacity: int
    player_count: int = 0
    tick_count: int = 0
    created_at: datetime = field(default_factory=datetime.utcnow)
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class Player:
    id: int
    telegram_id: int
    username: str | None
    locale: str
    role: PlayerRole
    is_banned: bool = False
    created_at: datetime = field(default_factory=datetime.utcnow)
    last_login_at: datetime | None = None
    world_id: int | None = None
    country_id: int | None = None


@dataclass(slots=True)
class Country:
    id: int
    world_id: int
    player_id: int | None
    code: str
    name: str
    flag_emoji: str = ""
    government: GovernmentType = GovernmentType.REPUBLIC
    population: int = 1_000_000
    treasury: float = 1_000_000.0
    debt: float = 0.0
    approval: float = 50.0
    stability: float = 50.0
    corruption: float = 10.0
    education: float = 50.0
    healthcare: float = 50.0
    electricity_balance: float = 0.0
    pollution: float = 0.0
    created_at: datetime = field(default_factory=datetime.utcnow)


@dataclass(slots=True)
class ResourceStock:
    id: int
    world_id: int
    country_id: int
    key: str
    amount: float
    capacity: float | None = None


@dataclass(slots=True)
class Building:
    id: int
    world_id: int
    country_id: int
    key: str
    level: int = 1
    status: BuildingStatus = BuildingStatus.PLANNED
    position_x: int = 0
    position_y: int = 0
    started_at: datetime | None = None
    completes_at: datetime | None = None
    produced_total: float = 0.0


@dataclass(slots=True)
class ResearchNode:
    id: int
    world_id: int
    country_id: int
    key: str
    status: ResearchStatus = ResearchStatus.LOCKED
    started_at: datetime | None = None
    completes_at: datetime | None = None


@dataclass(slots=True)
class Unit:
    id: int
    world_id: int
    country_id: int
    key: str
    count: int = 0
    state: UnitState = UnitState.IDLE
    region_id: int | None = None
    deployed_at: datetime | None = None


@dataclass(slots=True)
class Region:
    id: int
    world_id: int
    country_id: int | None
    name: str
    is_capital: bool = False
    population: int = 0
    area_km2: float = 0.0
    terrain: str = "plains"


@dataclass(slots=True)
class Order:
    id: int
    world_id: int
    country_id: int
    type: OrderType
    payload: dict[str, Any]
    created_at: datetime = field(default_factory=datetime.utcnow)
    scheduled_for: datetime | None = None
    executed_at: datetime | None = None


@dataclass(slots=True)
class MarketOrder:
    id: int
    world_id: int
    country_id: int
    side: MarketOrderSide
    resource_key: str
    quantity: float
    unit_price: float
    status: MarketOrderStatus = MarketOrderStatus.OPEN
    filled_quantity: float = 0.0
    created_at: datetime = field(default_factory=datetime.utcnow)
    expires_at: datetime | None = None


@dataclass(slots=True)
class War:
    id: int
    world_id: int
    attacker_id: int
    defender_id: int
    status: WarStatus = WarStatus.DECLARED
    war_type: WarType = WarType.CONVENTIONAL
    declared_at: datetime = field(default_factory=datetime.utcnow)
    ended_at: datetime | None = None
    winner_id: int | None = None
    attacker_war_score: float = 0.0
    defender_war_score: float = 0.0


@dataclass(slots=True)
class Diplomacy:
    id: int
    world_id: int
    country_a_id: int
    country_b_id: int
    status: DiplomaticStatus = DiplomaticStatus.NEUTRAL
    updated_at: datetime = field(default_factory=datetime.utcnow)


@dataclass(slots=True)
class Alliance:
    id: int
    world_id: int
    name: str
    tag: str
    leader_id: int
    treasury: float = 0.0
    created_at: datetime = field(default_factory=datetime.utcnow)


@dataclass(slots=True)
class AllianceMember:
    alliance_id: int
    country_id: int
    role: AllianceRole = AllianceRole.MEMBER
    joined_at: datetime = field(default_factory=datetime.utcnow)


@dataclass(slots=True)
class Mission:
    id: int
    world_id: int
    country_id: int
    key: str
    category: MissionCategory
    status: MissionStatus = MissionStatus.ACTIVE
    progress: float = 0.0
    claimed_at: datetime | None = None
    expires_at: datetime | None = None


@dataclass(slots=True)
class Notification:
    id: int
    player_id: int
    level: NotificationLevel
    title: str
    body: str
    data: dict[str, Any] = field(default_factory=dict)
    read_at: datetime | None = None
    created_at: datetime = field(default_factory=datetime.utcnow)


@dataclass(slots=True)
class GameEvent:
    id: int
    world_id: int
    key: str
    category: EventCategory
    payload: dict[str, Any]
    triggered_at: datetime = field(default_factory=datetime.utcnow)


# ----- Repository protocols (interfaces only) -----


class Repository(Protocol):
    """Marker protocol for repositories."""


class AsyncSessionLike(Protocol):
    """Subset of SQLAlchemy AsyncSession surface used by repositories."""

    async def execute(self, *args: Any, **kwargs: Any) -> Any: ...
    async def flush(self) -> None: ...
    async def commit(self) -> None: ...
    async def refresh(self, instance: Any) -> None: ...
    def add(self, instance: Any) -> None: ...
    async def delete(self, instance: Any) -> None: ...
