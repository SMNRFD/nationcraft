"""YAML config loader with live-reload, pluggable registry of game data."""
from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Any, Generic, TypeVar

import yaml
from pydantic import BaseModel

from .models import (
    BuildingDef,
    CountryDef,
    EventDef,
    MissionDef,
    ResourceDef,
    TechDef,
    UnitDef,
)

T = TypeVar("T", bound=BaseModel)


class YAMLConfigLoader:
    """Loads raw YAML files and parses them into typed Pydantic models.

    All gameplay static data is defined in YAML so designers can edit
    values without touching Python source code. The loader supports
    include-merge (``__include__: file.yml``) and live reload via mtime.
    """

    def __init__(self, base_dir: str | Path = "game/data") -> None:
        self.base_dir = Path(base_dir)
        self._cache: dict[str, tuple[float, Any]] = {}
        self._lock = threading.RLock()

    def load_raw(self, rel_path: str, *, force: bool = False) -> Any:
        path = self.base_dir / rel_path
        mtime = path.stat().st_mtime
        with self._lock:
            cached = self._cache.get(rel_path)
            if not force and cached and cached[0] == mtime:
                return cached[1]
            with path.open("r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
            data = self._resolve_includes(data, path.parent)
            self._cache[rel_path] = (mtime, data)
            return data

    def _resolve_includes(self, data: Any, cwd: Path) -> Any:
        if isinstance(data, dict):
            inc = data.pop("__include__", None)
            if inc:
                base = self._resolve_includes(yaml.safe_load((cwd / inc).read_text(encoding="utf-8")), cwd)
                if isinstance(base, dict):
                    base.update({k: self._resolve_includes(v, cwd) for k, v in data.items()})
                    return base
            return {k: self._resolve_includes(v, cwd) for k, v in data.items()}
        if isinstance(data, list):
            return [self._resolve_includes(x, cwd) for x in data]
        return data

    def load_collection(self, rel_path: str, model: type[T], key_field: str = "key") -> dict[str, T]:
        raw = self.load_raw(rel_path)
        items = raw.get("items") or raw.get("list") or raw
        if isinstance(items, dict):
            return {k: model(**{**v, key_field: v.get(key_field, k)}) for k, v in items.items()}
        return {item[key_field]: model(**item) for item in items}


class GameDataRegistry:
    """Single source of truth for all static game data.

    Provides live-reload semantics so that designers editing YAML files
    on a running server can refresh without restart via the admin API.
    """

    def __init__(self, base_dir: str | Path = "game/data") -> None:
        self.loader = YAMLConfigLoader(base_dir)
        self._last_reload: float = 0.0
        self._lock = threading.RLock()
        self._resources: dict[str, ResourceDef] = {}
        self._buildings: dict[str, BuildingDef] = {}
        self._units: dict[str, UnitDef] = {}
        self._techs: dict[str, TechDef] = {}
        self._countries: dict[str, CountryDef] = {}
        self._events: dict[str, EventDef] = {}
        self._missions: dict[str, MissionDef] = {}

    def reload(self) -> None:
        with self._lock:
            self._resources = self.loader.load_collection("resources.yaml", ResourceDef)
            self._buildings = self.loader.load_collection("buildings.yaml", BuildingDef)
            self._units = self.loader.load_collection("units.yaml", UnitDef)
            self._techs = self.loader.load_collection("techs.yaml", TechDef)
            self._countries = self.loader.load_collection("countries.yaml", CountryDef, key_field="code")
            self._events = self.loader.load_collection("events.yaml", EventDef)
            self._missions = self.loader.load_collection("missions.yaml", MissionDef)
            self._last_reload = time.time()

    # ---- accessors ----
    @property
    def resources(self) -> dict[str, ResourceDef]:
        self._ensure_loaded()
        return self._resources

    @property
    def buildings(self) -> dict[str, BuildingDef]:
        self._ensure_loaded()
        return self._buildings

    @property
    def units(self) -> dict[str, UnitDef]:
        self._ensure_loaded()
        return self._units

    @property
    def techs(self) -> dict[str, TechDef]:
        self._ensure_loaded()
        return self._techs

    @property
    def countries(self) -> dict[str, CountryDef]:
        self._ensure_loaded()
        return self._countries

    @property
    def events(self) -> dict[str, EventDef]:
        self._ensure_loaded()
        return self._events

    @property
    def missions(self) -> dict[str, MissionDef]:
        self._ensure_loaded()
        return self._missions

    def _ensure_loaded(self) -> None:
        if not self._last_reload:
            self.reload()

    def resource(self, key: str) -> ResourceDef:
        if key not in self.resources:
            raise KeyError(f"Unknown resource: {key}")
        return self.resources[key]

    def building(self, key: str) -> BuildingDef:
        if key not in self.buildings:
            raise KeyError(f"Unknown building: {key}")
        return self.buildings[key]

    def unit(self, key: str) -> UnitDef:
        if key not in self.units:
            raise KeyError(f"Unknown unit: {key}")
        return self.units[key]

    def tech(self, key: str) -> TechDef:
        if key not in self.techs:
            raise KeyError(f"Unknown tech: {key}")
        return self.techs[key]


# Singleton
game_data = GameDataRegistry(base_dir="game/data")
