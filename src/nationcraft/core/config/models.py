"""Pydantic definitions of all game-data configuration models."""
from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field, ConfigDict


class TickPhases(StrEnum):
    """Ordered tick phases. Plugins can subscribe to any phase."""

    PRE_TICK = "pre_tick"
    PRODUCTION = "production"
    POPULATION = "population"
    ECONOMY = "economy"
    RESEARCH = "research"
    CONSTRUCTION = "construction"
    MILITARY = "military"
    TRANSPORT = "transport"
    EVENTS = "events"
    MISSIONS = "missions"
    RANKINGS = "rankings"
    NOTIFICATIONS = "notifications"
    POST_TICK = "post_tick"


class CostBreakdown(BaseModel):
    """A mapping of resource key → amount, plus optional time cost."""

    model_config = ConfigDict(extra="allow")
    time_seconds: float = 0.0
    money: float = 0.0


class ResourceDef(BaseModel):
    """Static definition of a resource (food, oil, soldiers, …)."""

    key: str
    name: str
    category: str = "material"  # material | population | currency | research | military
    unit: str = ""
    icon: str = ""
    description: str = ""
    base_price: float = 1.0
    tradable: bool = True
    stackable: bool = True
    min_value: float = 0.0
    max_value: float | None = None
    hidden: bool = False


class BuildingDef(BaseModel):
    """Static definition of a building/factory/farm."""

    key: str
    name: str
    category: str = "industry"  # industry | power | military | research | transport | civic
    description: str = ""
    max_level: int = 10
    base_cost: dict[str, float] = Field(default_factory=dict)
    cost_growth: float = 1.5
    base_build_time: float = 60.0  # seconds at level 1
    production: dict[str, float] = Field(default_factory=dict)
    consumption: dict[str, float] = Field(default_factory=dict)
    storage: dict[str, float] = Field(default_factory=dict)
    workers_required: int = 0
    power_consumption: float = 0.0
    power_production: float = 0.0
    maintenance: dict[str, float] = Field(default_factory=dict)
    requires_tech: list[str] = Field(default_factory=list)
    requires_building: list[str] = Field(default_factory=list)
    upgrade_from: str | None = None


class UnitDef(BaseModel):
    """Static definition of a military unit."""

    key: str
    name: str
    category: str = "land"  # land | air | naval | missile | cyber | space
    description: str = ""
    attack: float = 0.0
    defense: float = 0.0
    health: float = 1.0
    speed: float = 1.0
    range_km: float = 0.0
    fuel_per_hour: float = 0.0
    crew: int = 0
    cost: dict[str, float] = Field(default_factory=dict)
    build_time: float = 60.0
    maintenance: dict[str, float] = Field(default_factory=dict)
    requires_tech: list[str] = Field(default_factory=list)
    requires_building: list[str] = Field(default_factory=list)
    transport_capacity: float = 0.0
    upgradeable_to: str | None = None


class TechDef(BaseModel):
    """Static definition of a research node in the technology tree."""

    key: str
    name: str
    branch: str = "industry"
    description: str = ""
    tier: int = 1
    research_cost: dict[str, float] = Field(default_factory=dict)
    research_time: float = 60.0
    requires: list[str] = Field(default_factory=list)
    effects: dict[str, float] = Field(default_factory=dict)
    unlocks_buildings: list[str] = Field(default_factory=list)
    unlocks_units: list[str] = Field(default_factory=list)


class CountryDef(BaseModel):
    """Static definition of a selectable country (template)."""

    code: str  # ISO 3166-1 alpha-2
    name: str
    region: str = ""
    flag_emoji: str = ""
    starting_population: int = 1_000_000
    starting_treasury: float = 1_000_000.0
    starting_resources: dict[str, float] = Field(default_factory=dict)
    starting_buildings: dict[str, int] = Field(default_factory=dict)
    starting_technologies: list[str] = Field(default_factory=list)
    traits: list[str] = Field(default_factory=list)
    description: str = ""


class EventDef(BaseModel):
    """Static definition of a random/server event."""

    key: str
    name: str
    category: str = "random"  # random | scheduled | natural | economic | political | holiday
    description: str = ""
    weight: float = 1.0
    min_world_age_ticks: int = 0
    cooldown_ticks: int = 0
    conditions: dict[str, Any] = Field(default_factory=dict)
    effects: dict[str, Any] = Field(default_factory=dict)


class MissionDef(BaseModel):
    """Static definition of a tutorial/daily/weekly mission or achievement."""

    key: str
    name: str
    category: str = "daily"  # tutorial | daily | weekly | achievement | seasonal
    description: str = ""
    objective: dict[str, Any]
    reward: dict[str, float] = Field(default_factory=dict)
    repeatable: bool = False
    expires_after_seconds: int | None = None
