"""DTOs for world, country, resource, production, market, military flows."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class WorldDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    slug: str
    status: str
    player_capacity: int
    player_count: int
    tick_count: int


class CountryDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    world_id: int
    player_id: int | None
    code: str
    name: str
    flag_emoji: str
    government: str
    population: int
    treasury: float
    approval: float
    stability: float
    corruption: float
    education: float
    healthcare: float
    electricity_balance: float


class ResourceStockDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    key: str
    amount: float
    capacity: float | None


class BuildRequest(BaseModel):
    building_key: str
    count: int = Field(default=1, ge=1, le=100)


class UpgradeRequest(BaseModel):
    building_id: int


class TrainRequest(BaseModel):
    unit_key: str
    count: int = Field(ge=1, le=10000)


class ResearchRequest(BaseModel):
    tech_key: str


class MarketOrderRequest(BaseModel):
    side: str  # buy | sell
    resource_key: str
    quantity: float = Field(gt=0)
    unit_price: float = Field(gt=0)
    expires_in_seconds: int | None = None


class DeclareWarRequest(BaseModel):
    defender_id: int
    war_type: str = "conventional"


class AttackRequest(BaseModel):
    war_id: int
    attacker_units: dict[str, int] = Field(default_factory=dict)
    defender_units: dict[str, int] = Field(default_factory=dict)
    target_region_id: int | None = None


class DiplomacyRequest(BaseModel):
    other_country_id: int
    status: str  # allied | friendly | hostile | embargo | trade_agreement


class AllianceCreateRequest(BaseModel):
    name: str = Field(min_length=3, max_length=64)
    tag: str = Field(min_length=2, max_length=8)


class AllianceInviteRequest(BaseModel):
    country_id: int


class MissionClaimRequest(BaseModel):
    mission_id: int


class NotificationDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    level: str
    title: str
    body: str
    data: dict[str, Any]
    read_at: datetime | None
    created_at: datetime


class RankingEntryDTO(BaseModel):
    country_id: int
    country_name: str
    score: float
    rank: int


class BroadcastRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4096)
    locale: str | None = None
