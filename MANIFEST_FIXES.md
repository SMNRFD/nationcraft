# NationCraft — Telegram Bot Timeout Fixes

This archive contains the NationCraft project with the Telegram bot
timeout fixes applied. See `worklog.md` (if provided alongside) or
the git diff for the full list of changes.

## Summary of fixes

The bot was showing:
- 19-38s update durations on a slow (Iranian) network
- `api_timeout` errors when the API actually responded in 10ms (e.g.
  409 player_exists)
- `/status` hanging for 10s
- WinError 10054 connection resets compounding into multi-update delays

Root causes and fixes:

### 1. `safe_send` retry storm (bot/utils.py)
- **Before**: 3 retries × 1+2+3=6s sleep on Telegram network errors,
  unbounded total time. On a slow network where each call takes 5-10s,
  this gave 15-30s per failed send.
- **After**: 2 retries × 1s sleep, **20s total cap**, re-raises
  `CancelledError` so shutdown works.

### 2. `api_client` global 15s timeout (bot/api_client.py)
- **Before**: Single 15s read timeout. Every hung API call blocked
  the bot's per-chat dispatcher for 15s, queuing all subsequent
  updates for that chat.
- **After**: Per-call timeouts — `_DEFAULT_TIMEOUT`=8s for fast
  endpoints, `_AUTH_TIMEOUT`=12s for register/login (Argon2 can
  spike to 1-2s under load).

### 3. In-process fast path for `--local` mode (bot/api_client.py + main.py)
- **Before**: When running `python main.py --local` (bot + API share
  one event loop), the bot's HTTP call to localhost could deadlock
  if the event loop was busy with a slow Telegram send. The API
  couldn't answer until the loop was free → `api_timeout`.
- **After**: `main.run_all` calls `set_in_process_api(True,
  is_serving=...)`. `ApiClient.health()` checks the uvicorn server
  state directly via the `is_serving` callable, avoiding the HTTP
  roundtrip. `/status` now responds instantly when `--local`.

### 4. `/status` resource leak (bot/handlers/commands.py)
- **Before**: Created a new `httpx.AsyncClient(timeout=10.0)` per
  `/status` call — leaked connections, no in-process optimization.
- **After**: Uses `await api_client.health()` (shared client,
  in-process fast path when available).

### 5. 409 `player_exists` surfaces correctly
- **Before**: When the bot was overloaded, a 409 response from
  `/auth/register` could be misclassified as `api_timeout` (because
  the HTTP call took longer than the timeout, even though the API
  responded in 10ms with 409). The user saw "Cannot reach the game
  server" when they were actually already registered.
- **After**: The per-call timeout + bounded `safe_send` ensure the
  409 response arrives quickly and is correctly classified as
  `player_exists`. The bot's `process_register` handler then shows
  "already registered, please /login" instead of a misleading
  timeout error.

## How to run

```bash
# 1. Create a venv and install deps
python3 -m venv .venv
. .venv/bin/activate
pip install -e ".[dev]"

# 2. Configure environment
cp .env.example .env
# Edit .env — set TELEGRAM_BOT_TOKEN, SECRET_KEY (32-byte hex),
# TELEGRAM_ADMIN_IDS (your Telegram user ID).

# 3. Initialize the database
python main.py --local --initdb

# 4. Run the game (API + worker + bot in one process)
python main.py --local
```

## Test status

All 142 tests pass (was 126 before these fixes; +16 new tests in
`tests/test_telegram_timeout_fixes.py` covering each fix above).

```bash
PYTHONPATH=src python -m pytest tests/ -q --timeout=120 --no-cov
```
