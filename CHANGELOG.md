# Changelog

All notable changes to NationCraft are documented here.
Format based on [Keep a Changelog](https://keepachangelog.com/),
and this project adheres to [Semantic Versioning](https://semver.org/).

## [1.0.1] — 2026-07-28

### Fixed — Critical Game-Breaking Bugs
- **Tech tree deadlock for non-Japan players:** `research_center` requires
  `electronics: 30` to build, but no building produced `electronics`.
  Only Japan started with electronics (5000), so every other country
  could never build a research_center, never produce research_points,
  and never research any tech. Added the **`electronics_factory`** building
  (no tech prereq, produces electronics from steel + electricity) so the
  tech tree is now accessible to all countries.
- **Air/naval warfare deadlock:** `fuel` was consumed by tanks, fighters,
  ships, missiles, and the `aircraft_factory` building, but no building
  produced it and no country started with it. Added the **`oil_refinery`**
  building (produces fuel from oil + electricity).
- **Nuclear path deadlock:** `uranium` was consumed by `icbm` units and
  `nuclear_power_plant`, but no building produced it and only 3 countries
  started with limited amounts. Added the **`uranium_mine`** building
  (produces uranium from electricity + water).
- **Stone was a finite resource:** All 14 countries started with 2000-5000
  stone, but no building produced it. Once depleted, players could no
  longer build water_wells, coal_mines, iron_mines, coal_power_plants,
  steel_mills, or warehouses. Added the **`quarry`** building (produces
  stone from wood + money).
- **`nuclear_power_plant` was permanently unbuildable:** it required
  `concrete: 200`, but `concrete` is not a defined resource and has no
  producer. Replaced with `stone: 500` (which is now producible by the
  quarry).

### Fixed — Shutdown & Runtime Bugs
- **`asyncio.CancelledError` traceback at shutdown:** running
  `python main.py --local` (all-in-one mode) and pressing Ctrl+C printed
  a scary traceback from starlette's lifespan handler. Root cause:
  `run_all` cancelled the uvicorn task abruptly. Fix: store the uvicorn
  server and TickRunner as module-level handles; on SIGINT, request
  graceful exit via `server.should_exit = True` and `runner.stop()`,
  then wait up to 10s before force-cancelling.
- **`--local` mode logged a Redis warning every startup:** the override
  set `REDIS_URL=redis://localhost:6379/0` which always failed. Now
  `--local` clears `REDIS_URL` entirely; the API logs
  `api.redis.skipped` (info) instead of `api.redis.unavailable`
  (warning), and `RedisCache.enabled=False` so the rate limiter
  falls back to in-memory without trying to connect.
- **`space_race.tick.bonus` logged every tick even when reactors=0:**
  pure log noise. Now only logs when at least one fusion reactor exists.
- **3 ruff F821 (undefined-name) bugs:** `LogoutRequest` was used in
  `auth_service.py` annotations but not imported; `aiohttp` was used
  in a string annotation in `bot/app.py` but only imported inside a
  function; `MarketOrderSide` was used in `domain/repositories/__init__.py`
  Protocol but not imported. All three are now properly imported.

### Added — API Endpoint UX Improvements
- `GET /production/buildings/catalog` — returns the static catalog of all
  buildable buildings with their cost, production, consumption, prereqs.
- `GET /production/research` — returns the catalog of all researchable
  techs plus the player's current status per tech (locked / available /
  in_progress / completed).
- `GET /military/units/catalog` — returns the static catalog of all
  trainable units with their cost, attack, defense, prereqs.
- These endpoints let clients render build/research/train menus without
  hard-coding the catalog.

### Tests
- Added `tests/test_latest_bugfixes.py` with 13 regression tests covering
  all the above fixes (new buildings, F821 imports, new endpoints,
  RedisCache.enabled flag).
- Total: **126 tests passing** (113 original + 13 new).

## [1.0.0] — 2026-07-27

### Added
- Initial production release.
- Clean Architecture: domain, application, infrastructure, presentation.
- FastAPI REST API with JWT (access + refresh), Argon2id, rate limiting,
  audit logging, admin endpoints.
- aiogram 3.x Telegram bot with inline keyboards, paginated lists,
  breadcrumb navigation, context menus, message editing.
- Tick engine with 13 ordered phases (production → research →
  population → events → missions → …).
- Plugin system: auto-discovery, manifest, lifecycle, stable Plugin API.
- Extension system: hookable formulas (production, combat, population,
  tick phases).
- Async event bus with priority, wildcard, error isolation.
- Game systems: worlds, countries, resources, production, research,
  military, war & combat, market (order book), alliances, diplomacy,
  missions, notifications, rankings, events, population simulation.
- Game data: 27 resources, 22 buildings, 22 units, 22 techs, 14
  countries, 11 events, 9 missions (YAML-driven, hot-reloadable).
- Localization: English + Persian (RTL).
- PostgreSQL schema (16 tables, soft deletes, JSONB metadata, indexes).
- Alembic migration `0001_initial`.
- Test suite: unit, integration, API, plugin, simulation.
- Docker Compose stack (postgres, redis, api, worker, bot).
- Documentation: GDD, SAD, API, plugins, extensions, configuration,
  ERD, deployment, tick engine, localization, contributing.
- Sample plugin (`space_race`) demonstrating all four extension modes.
- Sample extension (`hardcore_economy`) demonstrating hook overrides.
