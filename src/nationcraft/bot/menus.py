"""Plugin-extensible menu & command registries (used by the Plugin API)."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass(slots=True)
class MenuEntry:
    menu_id: str
    handler: Callable[..., Any]
    plugin_id: str | None = None


@dataclass(slots=True)
class CommandEntry:
    command: str
    handler: Callable[..., Any]
    plugin_id: str | None = None


class _MenuRegistry:
    def __init__(self) -> None:
        self._menus: dict[str, MenuEntry] = {}
        self._commands: dict[str, CommandEntry] = {}

    def register_menu(self, menu_id: str, handler: Callable[..., Any], *, plugin_id: str | None = None) -> None:
        self._menus[menu_id] = MenuEntry(menu_id=menu_id, handler=handler, plugin_id=plugin_id)

    def register_command(self, command: str, handler: Callable[..., Any], *, plugin_id: str | None = None) -> None:
        self._commands[command.lower()] = CommandEntry(command=command.lower(), handler=handler, plugin_id=plugin_id)

    def get_menu(self, menu_id: str) -> MenuEntry | None:
        return self._menus.get(menu_id)

    def get_command(self, command: str) -> CommandEntry | None:
        return self._commands.get(command.lower())

    def all_menus(self) -> list[MenuEntry]:
        return list(self._menus.values())

    def all_commands(self) -> list[CommandEntry]:
        return list(self._commands.values())

    def clear_plugin(self, plugin_id: str) -> None:
        self._menus = {k: v for k, v in self._menus.items() if v.plugin_id != plugin_id}
        self._commands = {k: v for k, v in self._commands.items() if v.plugin_id != plugin_id}


menu_registry = _MenuRegistry()
command_registry = _MenuRegistry()
