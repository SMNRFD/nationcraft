# Software Architecture Document (SAD)

## 1. Overview

NationCraft is built with **Clean Architecture**: dependency direction
always points *inward* — from presentation toward domain. The domain
core has no knowledge of databases, frameworks, or Telegram.

```
┌────────────────────────────────────────────────────────────┐
│ Presentation                                               │
│   ┌───────────────┐   ┌──────────────────┐                 │
│   │ FastAPI REST  │   │ aiogram Bot      │                 │
│   └───────┬───────┘   └────────┬─────────┘                 │
├───────────┼────────────────────┼──────────────────────────-┤
│ Application (services, DTOs)                                │
│   AuthService, WorldService, CountryService,                │
│   ProductionService, MarketService, WarService, ...        │
├────────────────────────────────────────────────────────────-┤
│ Domain (entities, value objects, enums, repository          │
│         protocols, domain events)                          │
├────────────────────────────────────────────────────────────-┤
│ Infrastructure (SQLAlchemy, Redis, JWT, Argon2, plugins)   │
└────────────────────────────────────────────────────────────┘
```

## 2. Layer responsibilities

### Domain (`src/nationcraft/domain/`)
Pure Python: dataclasses for entities, frozen dataclasses for value
objects, `StrEnum` for enumerations, `Protocol` classes for repository
interfaces, and a catalog of well-known event type strings. **No
SQLAlchemy, no FastAPI, no aiogram imports here.**

### Application (`src/nationcraft/application/`)
Use-case orchestration. Each service depends on repository protocols
(not concrete SQLAlchemy repos) and emits domain events via the event
bus. DTOs (`pydantic` v2) define the wire shape between application and
presentation.

### Infrastructure (`src/nationcraft/infrastructure/`)
Concrete implementations: SQLAlchemy ORM models, repository classes,
Redis cache, JWT utilities, Argon2 hasher, rate limiter, audit log
writer.

### Core (`src/nationcraft/core/`)
Cross-cutting primitives used by every layer: configuration, event bus,
extension hooks, plugin system, i18n, tick engine, logging, exceptions.

### Presentation
- **`src/nationcraft/api/`** — FastAPI routers, middleware, dependencies,
  envelope schema. Calls application services directly.
- **`src/nationcraft/bot/`** — aiogram bot. Talks to the backend *only*
  via the REST API (`bot.api_client`). Never imports application
  services directly.

## 3. Dependency direction (strict)

```
bot  ──►  api  ──►  application  ──►  domain
                          │
                          ▼
                  infrastructure  ──►  domain
                          │
                          ▼
                       core
```

**The domain layer imports nothing from infrastructure.** Repositories
are injected into services via constructor parameters typed as
`Protocol`s, enabling easy mocking in tests.

## 4. Event bus

`nationcraft.core.events.event_bus` is a process-wide async bus.
Subscribers register with priority (`HIGHEST` → `MONITOR`) and may be
sync or async. Handlers that throw do not block other handlers.

Domain events are cataloged in `nationcraft.domain.events` to avoid
string typos.

## 5. Extension & hook system

Hooks are named extension points (e.g. `production.output`,
`combat.resolve`, `tick.phase.production`). Extensions register handlers
via `@hook(name)` decorator; the registry runs handlers in priority
order, chaining the return value. The first handler receives the
default result (computed by the service); subsequent handlers receive
the previous handler's output.

This lets extensions override **any** formula without monkey-patching.

## 6. Plugin system

A plugin is a directory under `plugins/` containing a `plugin.json`
manifest and a `plugin.py` entrypoint. At startup the
`PluginLoader.discover()` scans `PLUGINS_DIRS`, parses manifests, and
`PluginRegistry.load_all()` imports each plugin module and calls its
`register(ctx)` function with a stable `PluginContext`.

The `PluginContext` exposes a `PluginAPI` with methods to register new
content (resources, buildings, units, techs, countries, events,
missions), subscribe to events, register hooks, and register bot
menus/commands. Plugins can be enabled/disabled at runtime via the
admin API.

## 7. Tick engine

`TickEngine` holds an ordered list of phase handlers. `TickRunner`
sleeps for `TICK_INTERVAL_SECONDS`, lists all active worlds, and runs
the engine per world. Built-in handlers cover production, research,
population, events, and missions. Plugins add behavior via the
`tick.phase.<name>` hook.

## 8. Configuration

Layered:

1. **Defaults** in `core.config.settings.Settings` (pydantic-settings).
2. **`.env` file** (auto-loaded).
3. **Environment variables** (highest precedence).
4. **YAML game data** (`game/data/*.yaml`) — hot-reloadable via the
   admin API.
5. **Plugin config** stored in the `plugin_states` table.

## 9. Database

PostgreSQL with:

- BigInt primary keys.
- `JSONB` columns for free-form metadata (so plugins can extend rows
  without migrations).
- Foreign keys with explicit `ON DELETE` policies.
- Soft deletes via `deleted_at` on `worlds` and `countries`.
- Indexes on hot paths (market matching, country/world lookups,
  notifications by player).
- Audit log table for admin actions.

## 10. Caching

Redis (`infrastructure.cache.RedisCache`) is used for:

- Rate-limit counters (sliding window via sorted sets).
- Future: hot-path reads (leaderboards, country snapshots).

## 11. Security

- **Password hashing**: Argon2id (memory 64 MiB, 3 iterations, parallel 2).
- **JWT**: HS256, access (15 min) + refresh (30 days), rotation on
  refresh, server-side session records for revocation.
- **Rate limiting**: per-user and per-endpoint sliding windows.
- **Permissions**: `PlayerRole` → `Permission` matrix enforced inside
  service methods, not just at the router boundary.
- **Input validation**: Pydantic v2 schemas on every endpoint.
- **SQL injection**: SQLAlchemy 2.x parameterized queries everywhere —
  no raw SQL.

## 12. Observability

- Structured JSON logs via `structlog`.
- Per-request `X-Request-Id` middleware.
- Audit log writes for admin actions.
- In-memory metrics registry exposed via `/admin/metrics`.

## 13. Testing strategy

| Layer | Type | Examples |
| --- | --- | --- |
| Domain | Unit | `test_value_objects.py` |
| Core | Unit | `test_event_bus.py`, `test_hooks.py`, `test_security.py`, `test_manifest.py` |
| Application | Integration | `test_auth_flow.py`, `test_world_country.py`, `test_market.py` |
| API | End-to-end | `test_endpoints.py` (httpx + ASGI transport) |
| Plugins | Loader | `test_plugin_loader.py` |
| Game | Simulation | `test_tick_simulation.py` (multiple real ticks) |

## 14. Trade-offs & alternatives

- **In-process event bus vs. message queue**: in-process is simpler
  and faster; the design allows swapping in Redis Streams or RabbitMQ
  by replacing the bus implementation.
- **Memory FSM storage for bot**: works for single-instance bots; for
  multi-instance, swap to Redis FSM storage.
- **Synchronous tick runner**: a single async task per world. For
  hundreds of worlds, partition by world_id and run multiple runners.
