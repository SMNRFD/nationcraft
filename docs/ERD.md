# Database ERD

## Overview

PostgreSQL with 16 tables. BigInt primary keys, JSONB metadata columns
on hot tables (so plugins can extend rows without migrations), soft
deletes on `worlds` and `countries`, full audit log.

## Entity-Relationship Diagram (text)

```
worlds ─┬─< countries ─┬─< resource_stocks
        │               ├─< buildings
        │               ├─< research_nodes
        │               ├─< units
        │               ├─< regions
        │               ├─< market_orders ──< market_trades
        │               ├─< diplomacies (M:M self via country_a_id, country_b_id)
        │               ├─< wars ──< battles
        │               ├─< alliance_members >── alliances
        │               ├─< missions
        │               └─< order_queue
        │
        └─< game_events

players ─┬─< sessions
         └─< notifications
         └─< audit_logs (actor)

plugin_states (independent)
```

## Tables

### `worlds`
- `id` PK
- `slug` UNIQUE
- `status` (open|full|closed|archived)
- `player_capacity`, `player_count` (CHECK: player_count <= player_capacity)
- `tick_count` BIGINT
- `meta` JSONB
- `deleted_at` (soft delete)

### `players`
- `id` PK
- `telegram_id` BIGINT UNIQUE
- `username`, `locale`, `role` (player|moderator|admin|owner)
- `is_banned`
- `password_hash` (Argon2id)
- `world_id` FK → worlds.id (SET NULL on delete)
- `country_id` FK → countries.id (SET NULL on delete)

### `sessions`
- `id` PK
- `player_id` FK → players.id (CASCADE)
- `refresh_token_hash` (sha256 of refresh JWT)
- `expires_at`, `revoked_at`
- `device_id`, `user_agent`, `ip_address`

### `countries`
- `id` PK
- `world_id` FK → worlds.id (CASCADE)
- `player_id` FK → players.id (SET NULL)
- `code` (ISO alpha-2), UNIQUE with `world_id`
- Demographic & economic columns (population, treasury, approval, …)
- `meta` JSONB
- `deleted_at`

### `resource_stocks`
- `id` PK
- `country_id` FK → countries.id (CASCADE)
- `key` (resource key)
- `amount` FLOAT
- `capacity` FLOAT NULL
- UNIQUE(country_id, key)

### `buildings`
- `id` PK
- `country_id` FK
- `key`, `level`, `status`, `started_at`, `completes_at`, `produced_total`

### `research_nodes`
- `id` PK
- `country_id` FK
- `key`, `status` (locked|available|in_progress|completed), `progress`
- UNIQUE(country_id, key)

### `units`
- `id` PK
- `country_id` FK
- `key`, `count`, `state`, `region_id`, `deployed_at`
- UNIQUE(country_id, key)

### `regions`
- `id` PK
- `world_id` FK, `country_id` FK (SET NULL)
- `name`, `is_capital`, `population`, `area_km2`, `terrain`

### `market_orders`
- `id` PK
- `world_id`, `country_id` FKs
- `side` (buy|sell), `resource_key`, `quantity`, `unit_price`
- `filled_quantity`, `status` (open|partial|filled|cancelled|expired)
- `expires_at`
- Index on (world_id, resource_key, side, status) for matching

### `market_trades`
- `id` PK
- `buy_order_id`, `sell_order_id` FKs
- `resource_key`, `quantity`, `unit_price`, `total`

### `diplomacies`
- `id` PK
- `country_a_id`, `country_b_id` FKs (CASCADE)
- `status` (neutral|allied|friendly|hostile|at_war|embargo|trade_agreement)
- UNIQUE(country_a_id, country_b_id)

### `wars`
- `id` PK
- `attacker_id`, `defender_id` FK → countries.id
- `status` (declared|active|ceasefire|ended|occupied)
- `war_type` (conventional|cyber|proxy|nuclear|civil)
- `winner_id`, `attacker_war_score`, `defender_war_score`

### `battles`
- `id` PK
- `war_id` FK
- `attacker_loss`, `defender_loss` JSONB
- `winner_id`, `occurred_at`

### `alliances` & `alliance_members`
- `alliances.id` PK, `world_id` FK, `name`, `tag`, `leader_id`, `treasury`
- `alliance_members.id` PK, `alliance_id` FK (CASCADE), `country_id` FK (CASCADE)
- `role` (leader|officer|member|recruit)
- UNIQUE(alliance_id, country_id)

### `missions`
- `id` PK
- `country_id` FK, `key`, `category`, `status`, `progress`, `claim_data` JSONB
- `claimed_at`, `expires_at`

### `notifications`
- `id` PK
- `player_id` FK (CASCADE)
- `level`, `title`, `body`, `data` JSONB, `read_at`

### `game_events`
- `id` PK
- `world_id` FK, `key`, `category`, `payload` JSONB, `triggered_at`

### `order_queue`
- `id` PK
- `country_id` FK, `type` (build|upgrade|train|research|trade|attack|diplomacy|policy)
- `payload` JSONB, `scheduled_for`, `executed_at`

### `audit_logs`
- `id` PK
- `actor_id`, `action`, `target_type`, `target_id`, `metadata` JSONB, `ip_address`

### `plugin_states`
- `id` PK
- `plugin_id` UNIQUE
- `enabled`, `config` JSONB, `version`

## Indexes

Key indexes for hot paths:

- `worlds` (status, deleted_at)
- `players` (telegram_id) UNIQUE
- `countries` (world_id, code) UNIQUE, (player_id), (deleted_at)
- `resource_stocks` (country_id, key) UNIQUE, (world_id, key)
- `buildings` (status, completes_at)
- `market_orders` (world_id, resource_key, side, status) — matching engine
- `notifications` (player_id, created_at DESC)
- `audit_logs` (action)
- `sessions` (refresh_token_hash), (expires_at)

## Migrations

Alembic manages schema evolution. Initial migration is
`alembic/versions/0001_initial.py`. Apply with:

```bash
make migrate
# or
alembic upgrade head
```

Generate a new migration after model changes:

```bash
make makemigrations -m "add new table"
```
