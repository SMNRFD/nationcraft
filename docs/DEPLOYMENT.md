# Deployment Guide

## 1. Prerequisites

- Docker 24+ and Docker Compose v2
- A Telegram bot token (from [@BotFather](https://t.me/BotFather))
- A server with at least 2 vCPUs, 4 GB RAM, 20 GB disk

## 2. Quick deploy (Docker Compose)

```bash
git clone <your-repo-url> nationcraft
cd nationcraft
cp .env.example .env
# Edit .env: set SECRET_KEY, TELEGRAM_BOT_TOKEN, TELEGRAM_ADMIN_IDS
docker-compose up -d --build
docker-compose exec api python -m nationcraft.cli initdb --worlds --data
```

This brings up:

| Service | Port | Purpose |
| --- | --- | --- |
| `postgres` | 5432 | Database |
| `redis` | 6379 | Cache & rate limiter |
| `api` | 8000 | FastAPI REST API |
| `worker` | — | Tick engine |
| `bot` | — | aiogram Telegram bot |

## 3. First-time setup

1. Apply migrations & seed data:
   ```bash
   docker-compose exec api python -m nationcraft.cli initdb --worlds --data
   ```
2. Send `/start` to your Telegram bot to register.
3. Promote your account to admin:
   ```sql
   UPDATE players SET role = 'owner' WHERE telegram_id = <your_id>;
   ```
   (Run inside the postgres container.)

## 4. Production hardening

### Secrets
- Generate `SECRET_KEY` with `python -c "import secrets; print(secrets.token_hex(32))"`.
- Store `.env` in a secrets manager (Vault, AWS SSM, Doppler).
- **Never** commit `.env` to git.

### Reverse proxy
Put Caddy / Nginx / Traefik in front of the API:

```caddy
api.yourdomain.com {
    reverse_proxy api:8000
}
```

### TLS
Caddy auto-issues Let's Encrypt certificates. For Nginx, use `certbot`.

### Backups
- Daily postgres dump:
  ```bash
  docker-compose exec postgres pg_dump -U nationcraft nationcraft | gzip > backup-$(date +%F).sql.gz
  ```
- Upload to S3 / B2 / GCS via lifecycle policy.

### Monitoring
- `/health` endpoint for liveness probes.
- Structured JSON logs → ship to Loki / Elasticsearch / Datadog.
- Use `X-Request-Id` for distributed tracing.

### Scaling
For larger player counts:

- **Horizontal API**: run multiple `api` containers behind a load balancer.
- **Worker sharding**: partition worlds across multiple `worker`
  containers by world_id modulo N. Set `WORLD_SHARD=<n>` and modify
  `TickRunner.run()` to filter worlds accordingly.
- **Redis cluster**: for rate limiting at very high QPS.
- **Read replicas**: route rankings & country snapshot reads to a PG
  read replica (configure a second SQLAlchemy engine).

## 5. Updating

```bash
git pull
docker-compose build
docker-compose up -d
docker-compose exec api python -m nationcraft.cli migrate
```

## 6. Rollback

```bash
# Roll back one migration
docker-compose exec api alembic downgrade -1
# Or roll back to a specific revision
docker-compose exec api alembic downgrade <revision_id>
```

## 7. Health checks

```bash
curl http://localhost:8000/health
# {"ok": true, "status": "ok", "version": "1.0.0"}
```

```bash
docker-compose ps
```

## 8. Logs

```bash
docker-compose logs -f api
docker-compose logs -f worker
docker-compose logs -f bot
```

All logs are structured JSON (`{"event": "http.request", "level": "info", ...}`).

## 9. Plugin management

- Drop a plugin directory under `plugins/` and restart the `api` and
  `worker` containers.
- Use `GET /admin/plugins` to list loaded plugins.
- Use `POST /admin/plugins/<id>/disable` to disable at runtime.

## 10. Disaster recovery

- Restore from the latest postgres backup:
  ```bash
  gunzip -c backup-2026-07-27.sql.gz | docker-compose exec -T postgres psql -U nationcraft nationcraft
  ```
- Restart all services.
- Verify world counts and tick numbers via the admin API.

## 11. Telegram webhook mode (optional)

For higher throughput than long polling:

1. Set `TELEGRAM_WEBHOOK_URL=https://bot.yourdomain.com/webhook`
2. Set `TELEGRAM_WEBHOOK_SECRET=<random-string>`
3. Expose the bot container on a public URL (e.g. via Traefik)
4. Restart the bot container with `--webhook` flag.

## 12. Capacity planning

Rough numbers on a 4 vCPU / 8 GB server:

| Players / world | Worlds | Ticks/min | CPU avg | RAM |
| --- | --- | --- | --- | --- |
| 200 | 5 | 5 | ~25% | 2.5 GB |
| 200 | 20 | 20 | ~70% | 4.5 GB |
| 500 | 5 | 5 | ~40% | 3.5 GB |

Beyond 20 active worlds, shard the worker.
