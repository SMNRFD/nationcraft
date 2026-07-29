# NationCraft — Testing Infrastructure

This document describes the testing infrastructure for NationCraft, including
the new mock Telegram Bot API server and the end-to-end tests that use it.

## Test Layers

NationCraft has four layers of tests, each exercising a different scope:

| Layer | What it tests | How to run | Count |
|-------|---------------|------------|-------|
| 1. Unit + Integration | Individual functions, services, API endpoints | `pytest tests/` | 164 tests |
| 2. Real Bot E2E | API + mock Telegram + real aiogram bot (separate processes) | `python scripts/e2e_real_bot_test.py` | 10 scenarios |
| 3. All-Services Smoke | `python main.py --local` (API + worker + bot in one process) | `python scripts/smoke_test_all_services.py` | 1 flow |
| 4. API E2E | API subprocess + HTTP client (auth flow) | `python scripts/e2e_smoke_test.py` | 1 flow |

Run all four layers:

```bash
source .venv/bin/activate
python -m pytest tests/ --no-cov -q
python scripts/e2e_real_bot_test.py
python scripts/smoke_test_all_services.py
python scripts/e2e_smoke_test.py
```

## Mock Telegram Bot API Server

`scripts/mock_telegram_server.py` is a **real** FastAPI server that implements
the subset of the Telegram Bot API that aiogram 3.x uses during polling. It
lets us test the bot's actual HTTP interaction with Telegram without needing
network access to `api.telegram.org` (which is blocked in some regions, e.g.
Iran).

### Why a mock Telegram server?

The user reported that the bot showed `api_timeout` errors even though the
local API was working fine. The root cause was:

1. The bot couldn't reach `api.telegram.org` (Iran network blocks it) →
   `WinError 10054`, `Request timeout error` in the polling loop.
2. Each `message.answer()` call blocked for up to 60s (aiogram's default
   timeout), queuing all subsequent updates.
3. The bot's HTTP calls to the local API sometimes timed out because the
   event loop was blocked by slow Telegram sends.

The mock Telegram server lets us reproduce and fix these issues in a
controlled environment.

### How it works

The mock server implements:
- `POST /bot{token}/getMe` — returns bot info
- `POST /bot{token}/getUpdates` — long-poll for updates (with `timeout` and `offset`)
- `POST /bot{token}/sendMessage` — stores and returns a fake Message
- `POST /bot{token}/editMessageText` — stores the edit
- `POST /bot{token}/answerCallbackQuery` — records the callback answer
- `POST /bot{token}/deleteWebhook`, `setWebhook`, `getWebhookInfo`, etc.

Plus test-helper endpoints (NOT part of the real Telegram API):
- `POST /test/push_message` — enqueue a private message update
- `POST /test/push_command` — enqueue a `/command` update
- `POST /test/push_callback` — enqueue a callback query (button click)
- `GET /test/sent_messages` — all messages the bot sent
- `GET /test/sent_messages/{chat_id}` — messages sent to a specific chat
- `GET /test/edited_messages` — all editMessageText calls
- `GET /test/answered_callbacks` — all answerCallbackQuery calls
- `GET /test/stats` — counters per Telegram method
- `POST /test/reset` — clear state (between tests)
- `GET /test/health` — liveness probe

### Running the mock server standalone

```bash
python scripts/mock_telegram_server.py --port 8081 --token 12345:fake
```

### Pointing the bot at the mock server

Set `TELEGRAM_API_BASE` in the bot's environment:

```bash
TELEGRAM_API_BASE=http://127.0.0.1:8081 \
TELEGRAM_BOT_TOKEN=12345:fake \
python main.py --only bot
```

The bot doesn't know it's not talking to the real Telegram.

## Key Fixes Applied

### 1. `TELEGRAM_API_BASE` is now honored

**Before**: The `TELEGRAM_API_BASE` setting existed in `settings.py` but was
never used — the bot always talked to `https://api.telegram.org`.

**After**: `bot/app.py` builds a `TelegramAPIServer` from
`settings.TELEGRAM_API_BASE` and assigns it to `bot.session.api`. This lets
the bot be pointed at a local mock server for testing, or at a self-hosted
Telegram Bot API server (https://github.com/tdlib/telegram-bot-api) for
production use in regions where `api.telegram.org` is blocked.

### 2. `--local` no longer hardcodes port 8000

**Before**: `_apply_local_overrides()` in `main.py` hardcoded
`API_BASE_URL=http://localhost:8000`, ignoring the `--port` CLI flag. If the
user ran `python main.py --local --port 8095`, the API listened on 8095 but
the bot's `API_BASE_URL` was still `:8000` → the bot couldn't reach the API.

**After**: `_apply_local_overrides()` builds `API_BASE_URL` from the current
`API_HOST` and `API_PORT` settings (which respect `--host` and `--port` CLI
flags and env vars). It also converts `0.0.0.0` (bind-all) to `localhost`
for the client URL (you can't connect to `0.0.0.0` as a client).

### 3. `api_client.register/login` retry on transient errors

**Before**: A single transient network error (timeout, connection reset)
caused the bot to show `api_timeout` to the user, even though a fresh
attempt would have succeeded.

**After**: `register()` and `login()` retry once on transient errors
(502/503/504, `api_timeout`, `api_unreachable`) with a 300ms backoff.
Definitive errors (401, 409, 422) are raised immediately without retry.

### 4. Mock Telegram server for end-to-end testing

**Before**: No way to test the bot's real HTTP interaction with Telegram
without network access to `api.telegram.org`.

**After**: `scripts/mock_telegram_server.py` provides a full mock that the
bot talks to as if it were the real Telegram. The e2e tests push updates
via the test-helper endpoints and verify the bot's replies via the
sent-messages endpoints.

## Test Files

| File | Purpose |
|------|---------|
| `scripts/mock_telegram_server.py` | Mock Telegram Bot API server (FastAPI) |
| `scripts/e2e_real_bot_test.py` | E2E test: API + mock Telegram + real bot, 10 scenarios |
| `scripts/smoke_test_all_services.py` | Smoke test: `python main.py --local` starts all services |
| `scripts/e2e_smoke_test.py` | Existing API e2e test (auth flow) |
| `tests/test_bot_e2e_enhancements.py` | Unit tests for the new enhancements (18 tests) |
| `tests/test_telegram_timeout_fixes.py` | Tests for the timeout/proxy fixes (20 tests) |
| `tests/test_bot_resilience.py` | Tests for Markdown/resilience fixes (25 tests) |

## Troubleshooting

### "Bot did not call getMe within 15s"

The bot couldn't reach the Telegram API server. Check:
1. Is the mock Telegram server running? (`curl http://127.0.0.1:8081/test/health`)
2. Is `TELEGRAM_API_BASE` set correctly in the bot's env?
3. Is `TELEGRAM_BOT_TOKEN` set?

### "api_timeout" or "api_unreachable" errors

The bot couldn't reach the local API. Check:
1. Is the API running? (`curl http://127.0.0.1:8000/health`)
2. Is `API_BASE_URL` set correctly? (Should match the API's host:port)
3. If using `--local --port N`, the `API_BASE_URL` is now built from
   `API_HOST:API_PORT` automatically (was hardcoded to `:8000` before).

### "Failed to fetch updates - TelegramNetworkError" on real Telegram

This means the bot can't reach `api.telegram.org` — common in regions where
Telegram is blocked/throttled (Iran, China, Russia). Set `TELEGRAM_PROXY`
in your `.env`:

```bash
TELEGRAM_PROXY=socks5://127.0.0.1:1080
# or
TELEGRAM_PROXY=http://127.0.0.1:8080
```

Alternatively, run a self-hosted Telegram Bot API server
(https://github.com/tdlib/telegram-bot-api) and set `TELEGRAM_API_BASE`
to point at it.
