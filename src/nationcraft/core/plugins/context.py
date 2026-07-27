"""Plugin context: stable API surface handed to plugins at load time."""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from nationcraft.core.events import EventBus, event_bus
from nationcraft.core.extensions import HookRegistry
from nationcraft.core.config import GameDataRegistry, game_data
from nationcraft.core.logging import get_logger

if TYPE_CHECKING:
    from nationcraft.core.plugins.api import PluginAPI


@dataclass(slots=True)
class PluginContext:
    """Bundled dependencies handed to a plugin's ``register()`` function.

    Plugins MUST only touch the core through this context. The context
    surface is the public Plugin API and is stable across minor versions.
    """

    plugin_id: str
    api: "PluginAPI"
    event_bus: EventBus = event_bus
    hook_registry: HookRegistry = HookRegistry.instance()
    game_data: GameDataRegistry = game_data
    logger: Any = None
    config: dict[str, Any] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.logger is None:
            self.logger = get_logger(f"plugin.{self.plugin_id}")
        if self.config is None:
            self.config = {}
