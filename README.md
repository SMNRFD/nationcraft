# NationCraft

> Production-quality plugin-driven Telegram nation-simulation game.

NationCraft is a persistent online multiplayer strategy game where players
become the ruler of a country inside a parallel world. Each world is
fully independent — when one fills up, the server automatically creates
another. The entire game is text-driven and delivered through a Telegram
bot, while all business logic runs on a FastAPI backend.

The codebase follows Clean Architecture: a domain core with no framework
coupling, an application layer of services, an infrastructure layer with
concrete persistence and security implementations, and presentation
layers (FastAPI REST API + aiogram Telegram bot) that depend only on
services, never on infrastructure.

## Highlights

- **Clean Architecture** with strict dependency direction (domain ← application ← infrastructure ← presentation).
- **Plugin system** with stable Plugin API, auto-discovery, dynamic enable/disable, and zero core modifications.
- **Extension system** with hookable formulas (production, combat, population, etc.).
- **Async event bus** with prioritized handlers, wildcard subscriptions, and error isolation.
- **Tick engine** with ordered phases (production → research → population → events → missions → …) — plugins can subscribe to any phase.
- **Configurable everything** — resources, buildings, units, technologies, events, missions, countries all defined in YAML.
- **REST API** with JWT (access + refresh), Argon2id password hashing, rate limiting, audit logging.
- **aiogram 3.x Telegram bot** with inline keyboards, paginated lists, breadcrumb navigation, context-aware menus, and message editing.
- **PostgreSQL + Redis** with proper indexing, foreign keys, soft deletes, and audit logs.
- **Localization (i18n)** with English and Persian (RTL) catalogs.
- **Tests** at every layer (unit, integration, API, plugin, simulation).
- **Production Docker Compose** for one-command deployment.

## Quick start

```bash
# 1. Configure environment.
cp .env.example .env
#   - Edit TELEGRAM_BOT_TOKEN, SECRET_KEY, ADMIN_IDS.

# 2. Launch everything (Postgres, Redis, API, worker, bot).
make up

# 3. Apply migrations and seed game data.
docker-compose exec api python -m nationcraft.cli initdb --worlds --data
```

Visit `http://localhost:8000/docs` for the interactive API docs, and
message your Telegram bot to start playing.

## Repository layout

```
nationcraft/
├── alembic/                    # Database migrations
├── deploy/                     # Deployment manifests
├── docs/                       # All project documentation
├── game/data/                  # Static game data (YAML)
│   ├── resources.yaml
│   ├── buildings.yaml
│   ├── units.yaml
│   ├── techs.yaml
│   ├── countries.yaml
│   ├── events.yaml
│   └── missions.yaml
├── locales/                    # i18n catalogs (en, fa)
├── plugins/                    # Plugin packages (auto-discovered)
│   └── space_race/
├── extensions/                 # Lightweight hook-based extensions
│   └── hardcore_economy.py
├── src/nationcraft/
│   ├── api/                    # FastAPI presentation layer
│   ├── application/            # Services & DTOs (use cases)
│   ├── bot/                    # aiogram Telegram bot
│   ├── core/                   # Cross-cutting: config, events, plugins, extensions, i18n, tick
│   ├── domain/                 # Entities, value objects, enums, repository protocols
│   ├── infrastructure/         # DB, repositories, cache, security, observability
│   └── workers/                # Tick worker entrypoint
├── tests/                      # unit / integration / api / plugin / simulation
├── docker-compose.yml
├── Dockerfile
├── pyproject.toml
└── Makefile
```

## Documentation

Comprehensive documentation lives in [`docs/`](docs/):

| Document | Purpose |
| --- | --- |
| [Game Design Document](docs/GDD.md) | Game systems, economy, combat, progression |
| [Software Architecture Document](docs/SAD.md) | Clean architecture, layers, dependencies |
| [API Reference](docs/API.md) | Every endpoint with request/response examples |
| [Plugin Development Guide](docs/PLUGINS.md) | How to write, package, and ship plugins |
| [Extension Guide](docs/EXTENSIONS.md) | Override game formulas via hooks |
| [Configuration Guide](docs/CONFIGURATION.md) | Every YAML schema and env var |
| [Database ERD](docs/ERD.md) | Full schema diagram and relationships |
| [Deployment Guide](docs/DEPLOYMENT.md) | Production deployment & ops |
| [Tick Engine](docs/TICK_ENGINE.md) | How the game loop works |
| [Localization Guide](docs/LOCALIZATION.md) | Adding new languages |
| [Contributing Guide](docs/CONTRIBUTING.md) | How to contribute |

## License

AGPL-3.0-or-later.

## Developers

Yasin Aryanfard Contact:
- Telegram: [@ysnrfd](https://t.me/ysnrfd) & [@ysnrfd3](https://t.me/ysnrfd3)
- GitHub: [ysnrfd](https://github.com/ysnrfd) & [SMNRFD](https://github.com/SMNRFD)
- Hugging Face: [ysn-rfd](https://huggingface.co/ysn-rfd)

Amir Hossein Contact:
- Telegram: [@Amir_hosseim](https://t.me/@Amir_hosseim)
- GitHub: [amirSAV](https://github.com/amirSAV)
