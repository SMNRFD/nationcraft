"""Plugin system: discovery, manifest, lifecycle, sandboxing, plugin API."""
from .manifest import PluginManifest
from .registry import PluginRegistry, PluginState
from .loader import PluginLoader
from .api import PluginAPI
from .context import PluginContext

__all__ = [
    "PluginManifest",
    "PluginRegistry",
    "PluginState",
    "PluginLoader",
    "PluginAPI",
    "PluginContext",
]
