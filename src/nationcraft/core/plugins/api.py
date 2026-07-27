"""Plugin API: stable surface plugins use to register resources, buildings, hooks, etc."""
from __future__ import annotations

from typing import Any, Awaitable, Callable

from nationcraft.core.config import (
    BuildingDef,
    CountryDef,
    EventDef,
    MissionDef,
    ResourceDef,
    TechDef,
    UnitDef,
)
from nationcraft.core.events import EventPriority
from nationcraft.core.extensions import HookPriority
from nationcraft.core.logging import get_logger


class PluginAPI:
    """Stable Plugin API surface.

    Plugins receive an instance via :class:`PluginContext` and use it to
    register new game content, hooks, event handlers, and bot UI.
    """

    def __init__(self, plugin_id: str) -> None:
        self.plugin_id = plugin_id
        self._log = get_logger(f"plugin.{plugin_id}")
        self._cleanup: list[Callable[[], Any]] = []

    # ---- content registration ----
    def register_resource(self, definition: ResourceDef) -> None:
        from nationcraft.core.config import game_data
        game_data._resources[definition.key] = definition
        self._log.info("plugin.resource.registered", key=definition.key)

    def register_building(self, definition: BuildingDef) -> None:
        from nationcraft.core.config import game_data
        game_data._buildings[definition.key] = definition
        self._log.info("plugin.building.registered", key=definition.key)

    def register_unit(self, definition: UnitDef) -> None:
        from nationcraft.core.config import game_data
        game_data._units[definition.key] = definition
        self._log.info("plugin.unit.registered", key=definition.key)

    def register_tech(self, definition: TechDef) -> None:
        from nationcraft.core.config import game_data
        game_data._techs[definition.key] = definition
        self._log.info("plugin.tech.registered", key=definition.key)

    def register_country(self, definition: CountryDef) -> None:
        from nationcraft.core.config import game_data
        game_data._countries[definition.code] = definition
        self._log.info("plugin.country.registered", code=definition.code)

    def register_event(self, definition: EventDef) -> None:
        from nationcraft.core.config import game_data
        game_data._events[definition.key] = definition
        self._log.info("plugin.event.registered", key=definition.key)

    def register_mission(self, definition: MissionDef) -> None:
        from nationcraft.core.config import game_data
        game_data._missions[definition.key] = definition
        self._log.info("plugin.mission.registered", key=definition.key)

    # ---- hook & event subscription ----
    def on_event(
        self,
        event_type: str,
        handler: Callable[..., Any],
        *,
        priority: EventPriority = EventPriority.NORMAL,
        once: bool = False,
    ) -> Callable[[], None]:
        unsub = self._event_bus().subscribe(event_type, handler, priority=priority, once=once)
        self._cleanup.append(unsub)
        return unsub

    def on_hook(
        self,
        hook_name: str,
        handler: Callable[..., Any],
        *,
        priority: int = HookPriority.DEFAULT,
    ) -> None:
        from nationcraft.core.extensions import HookRegistry
        HookRegistry.instance().register(hook_name, handler, priority=priority, plugin_id=self.plugin_id)

    # ---- bot menu/command registration (passed via callback) ----
    def register_bot_menu(self, menu_id: str, handler: Callable[..., Any]) -> None:
        from nationcraft.bot.menus import menu_registry
        menu_registry.register(menu_id, handler, plugin_id=self.plugin_id)
        self._log.info("plugin.menu.registered", menu_id=menu_id)

    def register_bot_command(self, command: str, handler: Callable[..., Any]) -> None:
        from nationcraft.bot.menus import command_registry
        command_registry.register(command, handler, plugin_id=self.plugin_id)
        self._log.info("plugin.command.registered", command=command)

    # ---- cleanup ----
    def unregister_all(self) -> None:
        for cb in self._cleanup:
            try:
                cb()
            except Exception:  # noqa: BLE001
                self._log.exception("plugin.cleanup.failed")
        self._cleanup.clear()
        from nationcraft.core.extensions import HookRegistry
        HookRegistry.instance().clear_plugin(self.plugin_id)

    def _event_bus(self):
        from nationcraft.core.events import event_bus
        return event_bus
