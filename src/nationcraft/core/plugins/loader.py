"""Discovers plugins from one or more directories."""
from __future__ import annotations

from pathlib import Path

from nationcraft.core.logging import get_logger
from nationcraft.core.plugins.manifest import PluginManifest
from nationcraft.core.plugins.registry import PluginRegistry, PluginState

log = get_logger(__name__)


class PluginLoader:
    """Scans ``plugins_dirs`` for directories containing ``plugin.json``."""

    def __init__(self, dirs: list[Path]) -> None:
        self.dirs = dirs
        self.registry = PluginRegistry.instance()

    def discover(self) -> int:
        count = 0
        for d in self.dirs:
            if not d.exists():
                log.warning("plugins.dir.missing", dir=str(d))
                continue
            for child in sorted(d.iterdir()):
                if not child.is_dir():
                    continue
                manifest_path = child / "plugin.json"
                if not manifest_path.exists():
                    continue
                try:
                    manifest = PluginManifest.from_path(manifest_path)
                    self.registry.add(manifest, child)
                    count += 1
                    log.info("plugin.discovered", plugin=manifest.id, dir=str(child))
                except Exception:  # noqa: BLE001
                    log.exception("plugin.discovery.failed", dir=str(child))
        return count

    def load_all(self) -> None:
        self.registry.load_all()

    def reload(self, plugin_id: str) -> None:
        rec = self.registry.get(plugin_id)
        if not rec:
            raise KeyError(plugin_id)
        self.registry.unload(plugin_id)
        rec.state = PluginState.DISCOVERED
        self.registry.load_all()
