"""Domain enumerations."""
from __future__ import annotations

from enum import StrEnum


class WorldStatus(StrEnum):
    OPEN = "open"
    FULL = "full"
    CLOSED = "closed"
    ARCHIVED = "archived"


class GovernmentType(StrEnum):
    DEMOCRACY = "democracy"
    REPUBLIC = "republic"
    MONARCHY = "monarchy"
    FEDERATION = "federation"
    DICTATORSHIP = "dictatorship"
    THEOCRACY = "theocracy"
    COMMUNIST = "communist"
    CUSTOM = "custom"


class DiplomaticStatus(StrEnum):
    NEUTRAL = "neutral"
    ALLIED = "allied"
    FRIENDLY = "friendly"
    HOSTILE = "hostile"
    AT_WAR = "at_war"
    EMBARGO = "embargo"
    TRADE_AGREEMENT = "trade_agreement"


class WarStatus(StrEnum):
    DECLARED = "declared"
    ACTIVE = "active"
    CEASEFIRE = "ceasefire"
    ENDED = "ended"
    OCCUPIED = "occupied"


class WarType(StrEnum):
    CONVENTIONAL = "conventional"
    CYBER = "cyber"
    PROXY = "proxy"
    NUCLEAR = "nuclear"
    CIVIL = "civil"


class BuildingStatus(StrEnum):
    PLANNED = "planned"
    UNDER_CONSTRUCTION = "under_construction"
    ACTIVE = "active"
    DAMAGED = "damaged"
    DESTROYED = "destroyed"
    PAUSED = "paused"


class ResearchStatus(StrEnum):
    LOCKED = "locked"
    AVAILABLE = "available"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"


class UnitState(StrEnum):
    IDLE = "idle"
    TRAINING = "training"
    DEPLOYED = "deployed"
    IN_COMBAT = "in_combat"
    MOVING = "moving"
    DESTROYED = "destroyed"


class OrderType(StrEnum):
    BUILD = "build"
    UPGRADE = "upgrade"
    TRAIN = "train"
    RESEARCH = "research"
    TRADE = "trade"
    ATTACK = "attack"
    DIPLOMACY = "diplomacy"
    POLICY = "policy"


class MarketOrderSide(StrEnum):
    BUY = "buy"
    SELL = "sell"


class MarketOrderStatus(StrEnum):
    OPEN = "open"
    PARTIAL = "partial"
    FILLED = "filled"
    CANCELLED = "cancelled"
    EXPIRED = "expired"


class MissionCategory(StrEnum):
    TUTORIAL = "tutorial"
    DAILY = "daily"
    WEEKLY = "weekly"
    ACHIEVEMENT = "achievement"
    SEASONAL = "seasonal"


class MissionStatus(StrEnum):
    LOCKED = "locked"
    ACTIVE = "active"
    COMPLETED = "completed"
    CLAIMED = "claimed"
    EXPIRED = "expired"


class NotificationLevel(StrEnum):
    INFO = "info"
    SUCCESS = "success"
    WARNING = "warning"
    DANGER = "danger"
    CRITICAL = "critical"


class PlayerRole(StrEnum):
    PLAYER = "player"
    MODERATOR = "moderator"
    ADMIN = "admin"
    OWNER = "owner"


class EventCategory(StrEnum):
    RANDOM = "random"
    SCHEDULED = "scheduled"
    NATURAL = "natural"
    ECONOMIC = "economic"
    POLITICAL = "political"
    HOLIDAY = "holiday"
    SERVER = "server"


class AllianceRole(StrEnum):
    LEADER = "leader"
    OFFICER = "officer"
    MEMBER = "member"
    RECRUIT = "recruit"
