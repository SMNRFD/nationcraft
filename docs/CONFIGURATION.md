# Configuration Guide

NationCraft is configurable at three levels:

1. **Environment variables / `.env`** — runtime secrets & infra URLs.
2. **YAML game data** — static game content (resources, buildings, …).
3. **Plugin config** — per-plugin settings in the `plugin_states` table.

## 1. Environment variables

See [`.env.example`](../.env.example) for the full list. Highlights:

| Variable | Default | Purpose |
| --- | --- | --- |
| `ENV` | `development` | `development` / `production` |
| `LOG_LEVEL` | `INFO` | Standard Python log level |
| `LOG_FORMAT` | `json` | `json` or `console` (colored) |
| `SECRET_KEY` | (dev only) | 32+ byte random hex; **must override in prod** |
| `JWT_ACCESS_TTL_SECONDS` | 900 | Access token lifetime |
| `JWT_REFRESH_TTL_SECONDS` | 2592000 | Refresh token lifetime (30 days) |
| `ARGON2_MEMORY_KIB` | 65536 | Argon2id memory cost |
| `ARGON2_ITERATIONS` | 3 | Argon2id time cost |
| `DATABASE_URL` | postgresql+asyncpg://… | SQLAlchemy async URL |
| `REDIS_URL` | redis://localhost:6379/0 | Redis URL |
| `API_HOST` / `API_PORT` | 0.0.0.0 / 8000 | FastAPI bind |
| `API_WORKERS` | 4 | uvicorn workers |
| `TELEGRAM_BOT_TOKEN` | — | From @BotFather |
| `TELEGRAM_ADMIN_IDS` | — | Comma-separated admin Telegram IDs |
| `TICK_INTERVAL_SECONDS` | 60 | Tick period |
| `WORLD_PLAYER_CAPACITY` | 200 | Max players per world |
| `WORLD_AUTO_CREATE` | true | Auto-create next world when one fills |
| `DEFAULT_LOCALE` | en | Default i18n locale |
| `SUPPORTED_LOCALES` | en,fa | Available locales |
| `PLUGINS_ENABLED` | true | Enable plugin discovery |
| `PLUGINS_DIRS` | plugins | Comma-separated plugin directories |
| `RATE_LIMIT_LOGIN_PER_MINUTE` | 5 | Login attempts per minute |
| `RATE_LIMIT_API_PER_MINUTE` | 300 | API calls per minute per player |
| `RATE_LIMIT_BOT_PER_USER_PER_MINUTE` | 120 | Bot interactions per minute |

## 2. YAML game data

All files live under `game/data/` and are hot-reloadable via the admin
endpoint `POST /admin/game-data/reload`.

### `resources.yaml`

```yaml
items:
  - key: food
    name: Food
    category: material      # material | currency | population | research | military
    icon: 🌾
    base_price: 5.0
    tradable: true
    stackable: true
    min_value: 0
    max_value: null         # null = unlimited
    hidden: false
    description: Feeds your population.
```

### `buildings.yaml`

```yaml
items:
  - key: farm
    name: Farm
    category: industry      # industry | power | military | research | transport | civic
    max_level: 10
    base_cost: {money: 1000, wood: 50}
    cost_growth: 1.4        # each level multiplies cost
    base_build_time: 60     # seconds at level 1
    production: {food: 50}  # per minute, per level
    consumption: {water: 5}
    storage: {}             # optional storage capacity
    workers_required: 10
    power_consumption: 5
    power_production: 0
    maintenance: {}         # per-minute upkeep
    requires_tech: []       # tech keys
    requires_building: []   # building keys
```

### `units.yaml`

```yaml
items:
  - key: infantry
    name: Infantry
    category: land          # land | air | naval | missile | cyber | space
    attack: 5
    defense: 8
    health: 10
    speed: 1
    range_km: 0
    fuel_per_hour: 0
    crew: 1
    cost: {money: 200, weapons: 1, food: 10}
    build_time: 60          # seconds per unit
    maintenance: {money: 1, food: 0.1}  # per unit per minute
    requires_tech: []
    requires_building: [barracks]
```

### `techs.yaml`

```yaml
items:
  - key: mechanical_engineering
    name: Mechanical Engineering
    branch: industry        # industry | military | energy | civic | space
    tier: 1
    research_cost: {money: 5000, research_points: 100}
    research_time: 600      # seconds
    requires: []            # tech keys
    effects: {production_bonus: 0.05}
    unlocks_buildings: [vehicle_factory]
    unlocks_units: [tank]
```

### `countries.yaml`

```yaml
items:
  - code: IR                # ISO 3166-1 alpha-2
    name: Iran
    region: middle_east
    flag_emoji: 🇮🇷
    starting_population: 85000000
    starting_treasury: 2000000
    starting_resources: {money: 2000000, food: 50000, oil: 20000}
    starting_buildings: {farm: 5, oil_field: 2}
    starting_technologies: []
    traits: [oil_rich, mountainous]
    description: A large Middle Eastern nation with abundant oil and gas reserves.
```

### `events.yaml`

```yaml
items:
  - key: drought
    name: Drought
    category: natural       # random | scheduled | natural | economic | political | holiday | server
    weight: 1.0             # relative probability multiplier
    min_world_age_ticks: 0  # event can't trigger before world is this old
    cooldown_ticks: 100
    effects: {food: -5000, water: -5000, approval: -2.0}
```

### `missions.yaml`

```yaml
items:
  - key: daily_food_reserve
    name: Daily: Stockpile 100k food
    category: daily         # tutorial | daily | weekly | achievement | seasonal
    objective: {metric: food, op: ">=", target: 100000}
    reward: {money: 100000, influence: 50}
    repeatable: true
    expires_after_seconds: 86400
```

## 3. Plugin configuration

Per-plugin config is stored in the `plugin_states` table and surfaced
to plugins via `ctx.config`. Use the admin API to update it (a future
release will add a dedicated admin endpoint for editing plugin config).

## 4. Live reload

YAML files can be edited and reloaded without restarting:

```bash
curl -X POST http://localhost:8000/admin/game-data/reload \
  -H "Authorization: Bearer <admin-token>"
```

Note: structural changes (new resource keys, removed buildings) only
affect new worlds; existing worlds keep their seeded state.

## 5. Secrets

Never commit `.env`. Rotate `SECRET_KEY` periodically — but note that
changing it invalidates all existing JWTs.
