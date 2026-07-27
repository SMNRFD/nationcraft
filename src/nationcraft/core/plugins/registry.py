"""Plugin lifecycle states and registry singleton."""
from __future__ import annotations

import importlib
import importlib.util
import sys
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any

from nationcraft.core.events import event_bus
from nationcraft.core.logging import get_logger
from nationcraft.core.plugins.api import PluginAPI
from nationcraft.core.plugins.context import PluginContext
from nationcraft.core.plugins.manifest import PluginManifest

log = get_logger(__name__)


class PluginState(StrEnum):
    DISCOVERED = "discovered"
    LOADED = "loaded"
    ENABLED = "enabled"
    DISABLED = "disabled"
    ERRORED = "errored"


@dataclass(slots=True)
class PluginRecord:
    manifest: PluginManifest
    state: PluginState = PluginState.DISCOVERED
    module: Any = None
    api: PluginAPI | None = None
    error: str | None = None
    path: Path | None = None
    config: dict[str, Any] = field(default_factory=dict)


class PluginRegistry:
    """Process-wide plugin registry."""

    _instance: "PluginRegistry | None" = None

    @classmethod
    def instance(cls) -> "PluginRegistry":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def __init__(self) -> None:
        self._plugins: dict[str, PluginRecord] = {}

    def add(self, manifest: PluginManifest, path: Path) -> PluginRecord:
        rec = PluginRecord(manifest=manifest, path=path)
        self._plugins[manifest.id] = rec
        return rec

    def get(self, plugin_id: str) -> PluginRecord | None:
        return self._plugins.get(plugin_id)

    def all(self) -> list[PluginRecord]:
        return list(self._plugins.values())

    def enabled(self) -> list[PluginRecord]:
        return [p for p in self._plugins.values() if p.state == PluginState.ENABLED]

    def set_state(self, plugin_id: str, state: PluginState, error: str | None = None) -> None:
        rec = self._plugins[plugin_id]
        rec.state = state
        rec.error = error

    def load_all(self, *, plugin_configs: dict[str, dict[str, Any]] | None = None) -> None:
        """Load every discovered plugin in dependency/load-order."""
        plugin_configs = plugin_configs or {}
        ordered = sorted(self._plugins.values(), key=lambda p: p.manifest.load_order)
        for rec in ordered:
            try:
                self._load_one(rec, plugin_configs.get(rec.manifest.id, {}))
            except Exception as exc:  # noqa: BLE001
                log.exception("plugin.load.failed", plugin=rec.manifest.id)
                rec.state = PluginState.ERRORED
                rec.error = str(exc)

    def _load_one(self, rec: PluginRecord, config: dict[str, Any]) -> None:
        manifest = rec.manifest
        # Load module from file path for directory plugins, or via dotted path.
        module_path = manifest.module or f"{manifest.id}.plugin"
        try:
            module = importlib.import_module(module_path)
        except ModuleNotFoundError:
            if rec.path is None:
                raise
            spec = importlib.util.spec_from_file_location(
                f"nationcraft_plugin_{manifest.id}", rec.path / manifest.entrypoint
            )
            if spec is None or spec.loader is None:
                raise
            module = importlib.util.module_from_spec(spec)
            sys.modules[spec.name] = module
            spec.loader.exec_module(module)

        api = PluginAPI(plugin_id=manifest.id)
        ctx = PluginContext(plugin_id=manifest.id, api=api, config=config)
        if hasattr(module, "register"):
            module.register(ctx)
        rec.module = module
        rec.api = api
        rec.config = config
        rec.state = PluginState.ENABLED
        log.info("plugin.loaded", plugin=manifest.id, version=manifest.version)
        # Best-effort event emission (won't crash if no loop is running).
        try:
            import asyncio
            from nationcraft.core.events import Event
            loop = asyncio.get_event_loop()
            if loop.is_running():
                loop.create_task(event_bus.publish(
                    Event(type="plugin.loaded",
                          payload={"plugin_id": manifest.id, "version": manifest.version})
                ))
        except RuntimeError:
            pass

    def unload(self, plugin_id: str) -> None:
        rec = self._plugins.get(plugin_id)
        if not rec or rec.state != PluginState.ENABLED:
            return
        if rec.api:
            rec.api.unregister_all()
        rec.state = PluginState.DISABLED
        log.info("plugin.unloaded", plugin=plugin_id)
