# Extension Guide

Extensions are lightweight hooks that override game calculations
**without modifying core source code**. Unlike plugins, extensions
don't have a manifest — they are simply Python modules that register
hook handlers via the `@hook(name)` decorator.

## 1. Hook concept

A **hook** is a named extension point. When the core needs to compute a
value (e.g. production output for a building), it calls:

```python
result = await HookRegistry.instance().invoke(
    "production.output", default_value, *args, **kwargs
)
```

Each registered handler runs in priority order. The first handler
receives `default_value` (computed by the core). Each subsequent
handler receives the previous handler's return value. The final return
value is what the core uses.

This means:

- An extension can **tweak** the default (multiply by 0.8, add a bonus…).
- An extension can **completely override** the default (return a
  different value, ignore input).
- Multiple extensions compose deterministically by priority.

## 2. Available hooks

| Hook name | Default | Args | Purpose |
| --- | --- | --- | --- |
| `production.output` | computed prod dict | `building, level, delta` | Modify building production |
| `combat.resolve` | BattleResult dataclass | `attacker_units, defender_units` | Override battle resolution |
| `population.unrest` | 0.0 | `approval, stability, pollution` | Compute unrest level 0–1 |
| `tick.phase.<phase>` | None | `TickContext` | Run extra logic in a tick phase |

More hooks will be added over time. Plugins may also define their own
hooks for other plugins to extend.

## 3. Writing an extension

Create a Python file under `extensions/`:

```python
# extensions/hardcore_economy.py
from nationcraft.core.extensions import HookPriority, hook


@hook("production.output", priority=HookPriority.LOW)
def nerf_production(prod, *, building=None, level=1, delta=60):
    """Reduce all production by 20% (hardcore mode)."""
    if not prod:
        return prod
    return {k: v * 0.8 for k, v in prod.items()}


@hook("combat.resolve", priority=HookPriority.HIGH)
def deadlier_combat(default, *, attacker_units=None, defender_units=None):
    """Make combat 50% more lethal."""
    if default is None:
        return default
    from dataclasses import replace
    new_a = {k: int(v * 1.5) for k, v in default.attacker_losses.items()}
    new_d = {k: int(v * 1.5) for k, v in default.defender_losses.items()}
    return replace(default, attacker_losses=new_a, defender_losses=new_d)
```

## 4. Priority

| Priority | Int | Use |
| --- | --- | --- |
| `HIGHEST` | 0 | Run first; can completely override |
| `HIGH` | 100 | Tweak before normal handlers |
| `DEFAULT` | 500 | Normal priority |
| `LOW` | 900 | Tweak after normal handlers |
| `LOWEST` | 1000 | Run last |
| `MONITOR` | — | Observers only; never mutate |

## 5. Loading extensions

Extensions are loaded as part of plugin discovery (any `*.py` file under
`extensions/` is imported at startup). To make this work, ensure
`extensions` is on the Python path (it is by default in the Docker
image — see `pyproject.toml` `src` config).

To register an extension programmatically (e.g. inside a plugin):

```python
from nationcraft.core.extensions import HookRegistry, HookPriority

def my_handler(prod, *, building=None, level=1, delta=60):
    ...

HookRegistry.instance().register(
    "production.output", my_handler, priority=HookPriority.LOW,
    plugin_id="my_plugin",
)
```

## 6. Difference from plugins

| Aspect | Plugin | Extension |
| --- | --- | --- |
| Manifest | Required (`plugin.json`) | None |
| Lifecycle | discover → load → unload | Imported once at startup |
| Capabilities | Register content, events, hooks, menus, commands | Hook handlers only |
| Use case | Whole new game systems | Tweak existing formulas |
| Cleanup | Automatic (via `api.unregister_all()`) | Manual (rarely needed) |

## 7. Example

See [`extensions/hardcore_economy.py`](../extensions/hardcore_economy.py)
for a working extension that nerfs production and makes combat deadlier.
