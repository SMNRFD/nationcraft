# API Reference

Base URL: `http://localhost:8000`

All responses use the standard envelope:

```json
{
  "ok": true,
  "data": { ... },
  "error": null
}
```

On error:

```json
{
  "ok": false,
  "data": null,
  "error": {
    "code": "validation_error",
    "message": "…",
    "details": null
  }
}
```

Every authenticated endpoint requires one of:

- `Authorization: Bearer <access_token>` header, or
- `X-Api-Token: <access_token>` header.

Tokens are obtained via `/auth/register` or `/auth/login`.

---

## Auth

### `POST /auth/register`

```json
// Request
{
  "telegram_id": 123456789,
  "username": "alice",
  "locale": "en",
  "password": "supersecret"
}

// Response (200)
{
  "ok": true,
  "data": {
    "access_token": "eyJhbGciOi...",
    "refresh_token": "eyJhbGciOi...",
    "token_type": "Bearer",
    "expires_in": 900,
    "player": {
      "id": 1,
      "telegram_id": 123456789,
      "username": "alice",
      "locale": "en",
      "role": "player",
      "is_banned": false,
      "world_id": null,
      "country_id": null
    }
  }
}
```

### `POST /auth/login`
Same body as register (minus `username` and `locale`).

### `POST /auth/refresh`
```json
{ "refresh_token": "…" }
```

### `POST /auth/logout`
```json
{ "refresh_token": "…" }
```

---

## Worlds

### `GET /worlds?only_open=true`
List open worlds.

### `GET /worlds/{world_id}`
Get a world by id.

---

## Countries

### `GET /countries/available/{world_id}`
Countries in the world that have no player yet.

### `GET /countries/world/{world_id}`
All countries in a world.

### `POST /countries/select`
```json
{ "world_id": 1, "country_code": "IR" }
```

### `POST /countries/abandon`
Abandon your current country.

### `GET /countries/me`
Full snapshot of your country (country, resources, buildings, units).

### `GET /countries/{country_id}`
Single country.

---

## Production

### `GET /production/buildings`
Your buildings.

### `POST /production/build`
```json
{ "building_key": "farm", "count": 1 }
```

### `POST /production/upgrade`
```json
{ "building_id": 42 }
```

### `POST /production/research`
```json
{ "tech_key": "mechanical_engineering" }
```

---

## Military

### `GET /military/units`
Your units.

### `POST /military/train`
```json
{ "unit_key": "infantry", "count": 10 }
```

### `POST /military/war/declare`
```json
{ "defender_id": 5, "war_type": "conventional" }
```

### `POST /military/war/attack`
```json
{
  "war_id": 1,
  "attacker_units": { "infantry": 100, "tank": 10 },
  "defender_units": { "infantry": 50 }
}
```

### `GET /military/wars`
Your active wars.

---

## Market

### `GET /market/orders`
Your market orders.

### `POST /market/order`
```json
{
  "side": "buy",
  "resource_key": "oil",
  "quantity": 100,
  "unit_price": 25,
  "expires_in_seconds": 86400
}
```

### `POST /market/cancel/{order_id}`
Cancel an open order; refunds the unfilled portion.

---

## Social

### Alliances

- `POST /social/alliance/create` — `{ "name": "Allies", "tag": "ALY" }`
- `POST /social/alliance/invite` — `{ "country_id": 5 }`
- `POST /social/alliance/join/{alliance_id}`
- `POST /social/alliance/leave`

### Diplomacy

- `POST /social/diplomacy` — `{ "other_country_id": 5, "status": "allied" }`
- `GET /social/diplomacy`

### Missions

- `GET /social/missions`
- `POST /social/mission/claim` — `{ "mission_id": 7 }`

### Notifications

- `GET /social/notifications?limit=20`
- `POST /social/notifications/{id}/read`

### Rankings

- `GET /social/rankings/{world_id}?metric=population&limit=50`

Available metrics: `population`, `treasury`, `approval`, `stability`,
`education`, `healthcare`, `military_power`, `gdp`, `research_points`.

---

## Admin

Admin endpoints require `role ∈ {admin, owner}` in the JWT.

- `POST /admin/broadcast` — `{ "message": "…", "locale": "en" }`
- `POST /admin/ban/{target_id}`
- `POST /admin/unban/{target_id}`
- `GET /admin/plugins`
- `POST /admin/plugins/{plugin_id}/disable`
- `POST /admin/game-data/reload`
- `GET /admin/metrics`

---

## Health

### `GET /health`
```json
{ "ok": true, "status": "ok", "version": "1.0.0" }
```

---

## Error codes

| Code | HTTP | Meaning |
| --- | --- | --- |
| `validation_error` | 422 | Request body failed schema validation |
| `not_found` | 404 | Resource not found |
| `conflict` | 409 | State conflict (e.g. country already taken) |
| `authentication_failed` | 401 | Missing or invalid token |
| `forbidden` | 403 | Insufficient permissions |
| `rate_limited` | 429 | Rate limit exceeded |
| `game_rule_violation` | 400 | Action violates game rules |
| `insufficient_resources` | 400 | Not enough resources to perform action |
| `plugin_error` | 500 | Plugin raised an exception |
| `internal_error` | 500 | Unhandled server error |
