# Changelog

All notable changes to NationCraft are documented here.
Format based on [Keep a Changelog](https://keepachangelog.com/),
and this project adheres to [Semantic Versioning](https://semver.org/).

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
