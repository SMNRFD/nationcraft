# Plugin Development Guide

A plugin is a self-contained package that extends NationCraft **without
modifying core source code**. This guide walks through everything you
need to ship your first plugin.

## 1. Layout

```
plugins/
└── my_plugin/
    ├── plugin.json     # Manifest (required)
    ├── plugin.py       # Entrypoint (required, name configurable)
    ├── README.md
    └── ...             # Any other modules/assets
```

Place the directory under any path listed in `PLUGINS_DIRS` (default
`plugins`). It will be auto-discovered at startup.

## 2. Manifest (`plugin.json`)

```json
{
  "id": "my_plugin",
  "name": "My Plugin",
  "version": "1.0.0",
  "api_version": "1.0",
  "author": "Your Name",
  "description": "Adds a new resource and a tick hook.",
  "entrypoint": "plugin.py",
  "permissions": ["tick.phase.production"],
  "dependencies": [
    {"name": "space_race", "optional": true}
  ],
  "load_order": 100,
  "enabled_by_default": true,
  "config_schema": {
    "my_setting": {"type": "number", "default": 1.0}
  }
}
```

### Fields

| Field | Type | Required | Description |
| --- | --- | --- | --- |
| `id` | string | yes | snake_case unique plugin id |
| `name` | string | yes | Human-readable name |
| `version` | string | yes | SemVer |
| `api_version` | string | no | Plugin API version (default `1.0`) |
| `entrypoint` | string | no | Python file (default `plugin.py`) |
| `permissions` | string[] | no | Capability tokens this plugin needs |
| `dependencies` | object[] | no | Other plugins this depends on |
| `load_order` | int | no | Lower loads first (default 100) |
| `enabled_by_default` | bool | no | Default state (default true) |
| `config_schema` | object | no | JSON-schema for plugin config |

## 3. Entrypoint (`plugin.py`)

Define a top-level `register(ctx)` function. The loader calls it with a
`PluginContext` exposing everything you need.

```python
from nationcraft.core.config import ResourceDef, BuildingDef
from nationcraft.core.extensions import HookPriority

def register(ctx):
    log = ctx.logger
    log.info("my_plugin.starting", config=ctx.config)

    # 1. Register static content
    ctx.api.register_resource(ResourceDef(
        key="antimatter",
        name="Antimatter",
        category="material",
        base_price=100000.0,
    ))
    ctx.api.register_building(BuildingDef(
        key="antimatter_plant",
        name="Antimatter Plant",
        category="power",
        base_cost={"money": 1_000_000},
        base_build_time=7200,
        production={"antimatter": 1},
        requires_tech=["antimatter_theory"],
    ))

    # 2. Subscribe to events
    async def on_war_declared(event):
        log.info("my_plugin.war_declared", payload=event.payload)
    ctx.api.on_event("war.declared", on_war_declared)

    # 3. Register a hook (chained formula override)
    def production_override(prod, *, building=None, level=1, delta=60):
        if building is not None and getattr(building, "key", None) == "antimatter_plant":
            prod = dict(prod)
            prod["antimatter"] = prod.get("antimatter", 0) + level * 0.1
        return prod
    ctx.api.on_hook("production.output", production_override,
                    priority=HookPriority.HIGH)

    # 4. Register a tick-phase hook
    async def production_phase(_default, ctx_tick):
        log.info("my_plugin.tick", world=ctx_tick.world_id, tick=ctx_tick.tick)
    ctx.api.on_hook("tick.phase.production", production_phase,
                    priority=HookPriority.LOW)

    # 5. Register a new bot menu
    async def my_menu(cb):
        await cb.message.edit_text("Antimatter menu (WIP)")
    ctx.api.register_bot_menu("antimatter:home", my_menu)
```

## 4. Plugin API surface (`ctx.api`)

### Content registration

- `register_resource(ResourceDef)`
- `register_building(BuildingDef)`
- `register_unit(UnitDef)`
- `register_tech(TechDef)`
- `register_country(CountryDef)`
- `register_event(EventDef)`
- `register_mission(MissionDef)`

### Event subscription

- `on_event(event_type, handler, *, priority=EventPriority.NORMAL, once=False)`

### Hook registration

- `on_hook(hook_name, handler, *, priority=HookPriority.DEFAULT)`

### Bot menu & command registration

- `register_bot_menu(menu_id, handler)`
- `register_bot_command(command, handler)`

## 5. Configuration

Plugin config is loaded from the `plugin_states` table (admin-managed
via the admin API) and passed to `register(ctx)` as `ctx.config`. Use
the manifest's `config_schema` to declare defaults.

```python
def register(ctx):
    bonus = float(ctx.config.get("bonus_research_per_tick", 1.0))
    ...
```

## 6. Lifecycle

- **Discovery**: at startup `PluginLoader.discover()` scans `PLUGINS_DIRS`.
- **Load**: `PluginRegistry.load_all()` imports modules in `load_order`
  and calls `register(ctx)`.
- **Unload**: `PluginRegistry.unload(id)` calls `api.unregister_all()`,
  which removes all event subscriptions, hook handlers, and bot
  menus/commands registered by the plugin.
- **Reload**: admin API can disable a plugin (calls unload); re-enable
  requires a restart in v1 (a future release will support full hot
  reload via module re-import).

## 7. Example

See [`plugins/space_race/`](../plugins/space_race/) for a complete
end-to-end example that registers a resource, a building, a tech, an
event handler, a production hook, and a tick-phase hook.

## 8. Best practices

- **Don't import from `nationcraft.infrastructure`** in your plugin —
  it couples you to the persistence layer. Use `ctx.api` instead.
- **Always log via `ctx.logger`** to get structured logging with the
  plugin id automatically.
- **Catch your own errors** in handlers — the core isolates them, but
  it's still good hygiene to handle expected cases.
- **Version your config schema** — bump `api_version` when you change
  the schema incompatibly.
- **Test your plugin** by placing it under `tests/plugin/` and using
  the existing `test_plugin_loader.py` pattern.
