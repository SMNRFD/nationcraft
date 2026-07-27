"""Configuration system: layered (env → YAML → defaults), live reloadable, strongly typed."""
from __future__ import annotations

from .settings import Settings, settings
from .loader import YAMLConfigLoader, GameDataRegistry, game_data
from .models import (
    ResourceDef,
    BuildingDef,
    UnitDef,
    TechDef,
    CountryDef,
    EventDef,
    MissionDef,
    TickPhases,
)

__all__ = [
    "Settings",
    "settings",
    "YAMLConfigLoader",
    "GameDataRegistry",
    "game_data",
    "ResourceDef",
    "BuildingDef",
    "UnitDef",
    "TechDef",
    "CountryDef",
    "EventDef",
    "MissionDef",
    "TickPhases",
]
