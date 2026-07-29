# NationCraft — Telegram Bot Timeout Fixes (Round 2)

This archive contains the NationCraft project with the Telegram bot
timeout fixes applied. See `worklog.md` (if provided alongside) or
the git diff for the full list of changes.

## What was broken

The user (in Iran) reported:
- 19-38s update durations on a slow network
- `api_timeout` errors when the API actually responded in 10ms (e.g. 409 player_exists)
- `/status` hanging for 10s
- WinError 10054 connection resets compounding into multi-update delays
- **NEW (Round 2)**: API returned 409 in 18ms, but the bot still took 13.4s to handle the update

## Root causes (across both rounds)

### Round 1 fixes (already in this archive)

#### 1. `safe_send` retry storm (bot/utils.py)
- **Before**: 3 retries × 1+2+3=6s sleep on Telegram network errors,
  unbounded total time. On a slow network where each call takes 5-10s,
  this gave 15-30s per failed send.
- **After**: 2 retries × 1s sleep, **20s total cap**, re-raises
  `CancelledError` so shutdown works.

#### 2. `api_client` global 15s timeout (bot/api_client.py)
- **Before**: Single 15s read timeout. Every hung API call blocked
  the bot's per-chat dispatcher for 15s, queuing all subsequent
  updates for that chat.
- **After**: Per-call timeouts — `_DEFAULT_TIMEOUT`=8s for fast
  endpoints, `_AUTH_TIMEOUT`=12s for register/login (Argon2 can
  spike to 1-2s under load).

#### 3. In-process fast path for `--local` mode (bot/api_client.py + main.py)
- **Before**: When running `python main.py --local` (bot + API share
  one event loop), the bot's HTTP call to localhost could deadlock
  if the event loop was busy with a slow Telegram send. The API
  couldn't answer until the loop was free → `api_timeout`.
- **After**: `main.run_all` calls `set_in_process_api(True,
  is_serving=...)`. `ApiClient.health()` checks the uvicorn server
  state directly via the `is_serving` callable, avoiding the HTTP
  roundtrip. `/status` now responds instantly when `--local`.

#### 4. `/status` resource leak (bot/handlers/commands.py)
- **Before**: Created a new `httpx.AsyncClient(timeout=10.0)` per
  `/status` call — leaked connections, no in-process optimization.
- **After**: Uses `await api_client.health()` (shared client,
  in-process fast path when available).

#### 5. 409 `player_exists` surfaces correctly
- **Before**: When the bot was overloaded, a 409 response from
  `/auth/register` could be misclassified as `api_timeout`.
- **After**: The per-call timeout + bounded `safe_send` ensure the
  409 response arrives quickly and is correctly classified as
  `player_exists`. The bot's `process_register` handler then shows
  "already registered, please /login".

### Round 2 fixes (NEW in this version)

#### 6. aiogram `AiohttpSession` was never actually configured (the 13s bottleneck)

**This was the REAL root cause of the 13.4s update durations.**

The user's logs showed:
```
http.request duration_ms=17.98 method=POST path=/auth/register status=409  ← API responded in 18ms
Update id=... Duration 13452 ms                                            ← bot still took 13.4s
```

The 13s was AFTER the API responded — it was the bot trying to call
`message.answer()` to send the "❌ Cannot reach..." reply to
api.telegram.org, which is throttled in Iran.

**Why was the bot blocking for 13s?** The bot/app.py code did:
```python
session = _build_aiohttp_session()  # built an aiohttp session with 60s timeout
bot.session._connector = session.connector  # silently did nothing
bot.session._timeout = session.timeout       # silently did nothing
bot.session._default_proxy = settings.TELEGRAM_PROXY  # silently did nothing
```

But `AiohttpSession` (aiogram's session class) **doesn't expose**
`_connector` or `_timeout` attributes. The assignments silently created
NEW instance attributes that were NEVER read by aiogram's internal
`create_session()` flow. Result: the bot was using **aiogram's
hardcoded DEFAULT 60s timeout** for every HTTP call to Telegram.

On a throttled Iranian network, a single `message.answer()` call
blocked for up to 60s (or got forcibly closed by the OS at ~5s with
WinError 10054), compounding into the 19-38s update durations and
"Cannot connect to host api.telegram.org:443" errors.

**Fix:**
- `bot/app.py` now constructs `AiohttpSession(proxy=..., timeout=...)`
  via the constructor (the ONLY way that works) and passes it to
  `Bot(session=session, ...)`.
- Added `TELEGRAM_REQUEST_TIMEOUT: float = 15.0` setting (was
  effectively 60s — aiogram's hardcoded default that the broken
  code couldn't override).
- Added loud warning at startup when `TELEGRAM_PROXY` is not set,
  informing users in regions where api.telegram.org is blocked/throttled
  (Iran, China, Russia) that they need to set up a proxy.
- Added `aiohttp-socks` to pyproject.toml dependencies (required for
  SOCKS5 proxy support — was missing before, so SOCKS proxies silently
  failed).

## How to run

```bash
# 1. Create a venv and install deps
python3 -m venv .venv
. .venv/bin/activate
pip install -e ".[dev]"

# 2. Configure environment
cp .env.example .env
# Edit .env:
#   - TELEGRAM_BOT_TOKEN (your bot token from @BotFather)
#   - SECRET_KEY (32-byte hex string: python -c "import secrets; print(secrets.token_hex(32))")
#   - TELEGRAM_ADMIN_IDS (your Telegram user ID — message @userinfobot to get it)
#   - TELEGRAM_PROXY (CRITICAL if you're in Iran/China/Russia where
#                     api.telegram.org is throttled. Examples:
#                     TELEGRAM_PROXY=socks5://127.0.0.1:1080
#                     TELEGRAM_PROXY=http://127.0.0.1:8080)
#   - TELEGRAM_REQUEST_TIMEOUT=15 (default; lower if you still see
#                                  "api_timeout" errors)

# 3. Initialize the database
python main.py --local --initdb

# 4. Run the game (API + worker + bot in one process)
python main.py --local
```

## Test status

All 146 tests pass (was 126 originally; +20 new tests in
`tests/test_telegram_timeout_fixes.py` covering each fix above).

```bash
PYTHONPATH=src python -m pytest tests/ -q --timeout=60 --no-cov
```

## Critical note for Iranian users

You MUST set `TELEGRAM_PROXY` in `.env` to a working proxy (SOCKS5 or
HTTP) that can reach `api.telegram.org`. Without a proxy, the bot will
see `WinError 10054` / `Cannot connect to host api.telegram.org:443`
on every long-poll cycle, and each `message.answer()` call will take
up to 15s (the new bounded timeout) before failing.

Recommended: install v2ray/xray and use a local SOCKS5 proxy:
```
TELEGRAM_PROXY=socks5://127.0.0.1:1080
```
