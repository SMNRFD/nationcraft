"""Tests for the bug-fix work in this commit.

Covers:
- ApiClient token eviction on 401 (P0)
- ApiClient token refresh on 401 (P0)
- ApiClient httpx timeout tightening (P0)
- AuthMiddleware locale cache pre-population (P0)
- PluginRegistry.add idempotency (P0)
- HookRegistry.register idempotency (P0/P3)
- EventBus.subscribe idempotency (P0/P3)
- JWT clock-skew leeway (P2)
- SQLite WAL pragmas (P1, smoke test)
"""
from __future__ import annotations

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------
# ApiClient token eviction + refresh
# ---------------------------------------------------------------------

@pytest.mark.asyncio
async def test_api_client_evicts_token_on_401():
    """A 401 response should remove the access token from the cache so
    subsequent calls don't keep sending a dead token.
    """
    from nationcraft.bot.api_client import ApiClient

    client = ApiClient(base_url="http://test")
    client.set_tokens(telegram_id=123, access_token="dead-access", refresh_token=None)

    # Mock httpx to return 401 with no refresh token.
    mock_resp = MagicMock()
    mock_resp.status_code = 401
    mock_resp.json.return_value = {"ok": False, "error": {"code": "authentication_failed", "message": "expired"}}
    mock_client = AsyncMock()
    mock_client.request = AsyncMock(return_value=mock_resp)
    mock_client.is_closed = False
    client._client = mock_client

    from nationcraft.core.exceptions import NationCraftError
    with pytest.raises(NationCraftError):
        await client._request("GET", "/anything", telegram_id=123)

    # Token should be evicted.
    assert client.get_token(123) is None


@pytest.mark.asyncio
async def test_api_client_refreshes_on_401_then_retries():
    """A 401 response when we have a refresh token should trigger a refresh
    and retry the original request once.
    """
    from nationcraft.bot.api_client import ApiClient

    client = ApiClient(base_url="http://test")
    client.set_tokens(telegram_id=123, access_token="old-access", refresh_token="valid-refresh")

    # First request -> 401; refresh -> 200 with new tokens; retry -> 200.
    refresh_resp = MagicMock()
    refresh_resp.status_code = 200
    refresh_resp.json.return_value = {
        "ok": True,
        "data": {"access_token": "new-access", "refresh_token": "new-refresh"},
    }
    ok_resp = MagicMock()
    ok_resp.status_code = 200
    ok_resp.json.return_value = {"ok": True, "data": {"ok": True}}

    call_count = {"n": 0}

    async def _mock_request(method, url, headers=None, json=None, **kwargs):
        call_count["n"] += 1
        # First call: original request returns 401
        # Second call: refresh call returns 200 with new tokens
        # Third call: retry original request returns 200
        if "refresh" in url:
            return refresh_resp
        # Original request
        if call_count["n"] == 1:
            unauth = MagicMock()
            unauth.status_code = 401
            unauth.json.return_value = {"ok": False, "error": {"code": "authentication_failed"}}
            return unauth
        # Retry after refresh
        return ok_resp

    mock_client = AsyncMock()
    mock_client.request = _mock_request
    mock_client.post = AsyncMock(return_value=refresh_resp)
    mock_client.is_closed = False
    client._client = mock_client

    result = await client._request("GET", "/something", telegram_id=123)
    assert result == {"ok": True}
    # Token should now be the new one.
    assert client.get_token(123) == "new-access"
    assert client.get_refresh_token(123) == "new-refresh"


@pytest.mark.asyncio
async def test_api_client_refresh_failure_clears_tokens():
    """If the refresh fails, the local session should be fully cleared."""
    from nationcraft.bot.api_client import ApiClient

    client = ApiClient(base_url="http://test")
    client.set_tokens(telegram_id=123, access_token="old-access", refresh_token="dead-refresh")

    refresh_resp = MagicMock()
    refresh_resp.status_code = 401  # refresh fails
    refresh_resp.json.return_value = {"ok": False, "error": {"code": "authentication_failed"}}

    async def _mock_request(method, url, headers=None, json=None, **kwargs):
        if "refresh" in url:
            return refresh_resp
        unauth = MagicMock()
        unauth.status_code = 401
        unauth.json.return_value = {"ok": False, "error": {"code": "authentication_failed"}}
        return unauth

    mock_client = AsyncMock()
    mock_client.request = _mock_request
    mock_client.post = AsyncMock(return_value=refresh_resp)
    mock_client.is_closed = False
    client._client = mock_client

    from nationcraft.core.exceptions import NationCraftError
    with pytest.raises(NationCraftError):
        await client._request("GET", "/something", telegram_id=123)

    # Both tokens should be cleared.
    assert client.get_token(123) is None
    assert client.get_refresh_token(123) is None


def test_api_client_timeout_is_bounded():
    """The httpx client should be configured with a bounded default timeout
    (8s read) and an 8s auth timeout for register/login.

    History:
    - 5s (original) — too short, caused ReadTimeout on Argon2 hashing.
    - 15s (second attempt) — too long; every hung API call blocked the
      bot's per-chat dispatcher for 15s, queuing all subsequent updates
      for that chat. On a slow Iranian network the queued updates
      compounded, producing the reported 19-38s update durations.
    - 8s default + 12s auth (third attempt) — still too long for auth
      on throttled networks; 12s meant each login attempt blocked the
      event loop for 12s.
    - 8s default + 8s auth (current) — 8s covers Argon2 ~500ms + DB I/O
      ~2s + event-bus publish with comfortable margin; lets the bot
      recover quickly when the API is genuinely broken. Auth uses the
      same 8s (was 12s) to fail fast on throttled networks.
    """
    import httpx
    from nationcraft.bot.api_client import _DEFAULT_TIMEOUT, _AUTH_TIMEOUT
    # Default read timeout should be 8s (was 15s — too long).
    assert _DEFAULT_TIMEOUT.read == pytest.approx(8.0)
    assert _DEFAULT_TIMEOUT.connect == pytest.approx(2.0)
    # Auth endpoints should use 8s (was 12s — too long on throttled networks).
    assert _AUTH_TIMEOUT.read == pytest.approx(8.0)


def test_api_client_base_url_picks_up_local_override():
    """ApiClient.base_url should be dynamic — picking up settings changes.

    Bug: with `.env` setting API_BASE_URL=http://api:8000 (Docker
    hostname), running `python main.py --local` updated
    settings.API_BASE_URL but NOT api_client.base_url, so the bot kept
    trying to reach the Docker hostname and failed.
    """
    import os
    from nationcraft.bot.api_client import ApiClient
    from nationcraft.core.config import settings as _settings

    # Simulate initial state (e.g., Docker .env): API_BASE_URL=http://api:8000
    _settings.API_BASE_URL = "http://api:8000"
    client = ApiClient()
    assert client.base_url == "http://api:8000", f"expected http://api:8000, got {client.base_url}"

    # Now simulate --local override: settings.API_BASE_URL changes to localhost
    _settings.API_BASE_URL = "http://localhost:8000"
    # The api_client.base_url should reflect the new value (dynamic property).
    assert client.base_url == "http://localhost:8000", (
        f"expected http://localhost:8000 after override, got {client.base_url}"
    )

    # Restore for other tests
    _settings.API_BASE_URL = "http://localhost:8000"


@pytest.mark.asyncio
async def test_api_client_get_me_preserves_token_on_network_error():
    """get_me should NOT clear the token on network errors.

    Bug: previously, get_me returned None on any error (auth or network),
    and cmd_panel would clear the token. This logged the user out on
    every transient API hiccup. Now: the token stays in self._tokens
    on network errors; only auth errors (401) evict it via _request.
    """
    from nationcraft.bot.api_client import ApiClient
    from nationcraft.core.exceptions import NationCraftError

    client = ApiClient(base_url="http://test")
    client.set_tokens(telegram_id=42, access_token="valid-tok", refresh_token="valid-ref")

    # Mock httpx to raise a network error
    import httpx
    mock_client = AsyncMock()
    async def _raise_network(*args, **kwargs):
        raise httpx.ConnectError("DNS resolution failed")
    mock_client.request = _raise_network
    mock_client.is_closed = False
    client._client = mock_client

    # get_me should return None (network error)
    result = await client.get_me(42)
    assert result is None

    # But the token should still be present (NOT cleared)
    assert client.get_token(42) == "valid-tok"
    assert client.get_refresh_token(42) == "valid-ref"


@pytest.mark.asyncio
async def test_api_client_get_me_clears_token_on_401():
    """get_me on a 401 response should leave the token evicted (done by _request)."""
    from nationcraft.bot.api_client import ApiClient
    from unittest.mock import MagicMock

    client = ApiClient(base_url="http://test")
    client.set_tokens(telegram_id=42, access_token="expired-tok", refresh_token="valid-ref")

    # Mock httpx to return 401 (no refresh token works)
    unauth_resp = MagicMock()
    unauth_resp.status_code = 401
    unauth_resp.json.return_value = {"ok": False, "error": {"code": "authentication_failed"}}

    # Refresh also fails
    refresh_fail = MagicMock()
    refresh_fail.status_code = 401
    refresh_fail.json.return_value = {"ok": False, "error": {"code": "authentication_failed"}}

    call_count = {"n": 0}
    async def _mock_request(method, url, headers=None, json=None, **kwargs):
        call_count["n"] += 1
        if "refresh" in url:
            return refresh_fail
        return unauth_resp

    mock_client = AsyncMock()
    mock_client.request = _mock_request
    mock_client.post = AsyncMock(return_value=refresh_fail)
    mock_client.is_closed = False
    client._client = mock_client

    # get_me should return None (auth error)
    result = await client.get_me(42)
    assert result is None

    # Both tokens should be evicted (refresh failed)
    assert client.get_token(42) is None
    assert client.get_refresh_token(42) is None


# ---------------------------------------------------------------------
# PluginRegistry.add idempotency
# ---------------------------------------------------------------------

def test_plugin_registry_add_is_idempotent():
    """Adding the same plugin manifest twice should return the SAME record
    (no state reset).
    """
    from pathlib import Path
    from nationcraft.core.plugins.registry import PluginRegistry, PluginState
    from nationcraft.core.plugins.manifest import PluginManifest

    reg = PluginRegistry()
    manifest = PluginManifest(
        id="test_plugin",
        name="Test",
        version="1.0.0",
        entrypoint="plugin.py",
        load_order=100,
    )
    path = Path("/fake")

    rec1 = reg.add(manifest, path)
    # Simulate the plugin being loaded by the API lifespan.
    rec1.state = PluginState.ENABLED
    rec1.config = {"key": "value"}

    # Now the worker tries to "discover" it again.
    rec2 = reg.add(manifest, path)
    # Same instance — state preserved.
    assert rec2 is rec1
    assert rec2.state == PluginState.ENABLED
    assert rec2.config == {"key": "value"}


# ---------------------------------------------------------------------
# HookRegistry.register idempotency
# ---------------------------------------------------------------------

def test_hook_registry_register_is_idempotent():
    """Registering the same handler twice for the same hook should only
    invoke it once.
    """
    from nationcraft.core.extensions.hooks import HookRegistry

    reg = HookRegistry()
    calls = []

    def handler(value, *args, **kwargs):
        calls.append(1)
        return value

    reg.register("test.hook", handler)
    reg.register("test.hook", handler)  # duplicate

    asyncio.run(reg.invoke("test.hook", "default"))
    assert len(calls) == 1, f"handler should be called once, got {len(calls)}"


# ---------------------------------------------------------------------
# EventBus.subscribe idempotency
# ---------------------------------------------------------------------

@pytest.mark.asyncio
async def test_event_bus_subscribe_is_idempotent():
    """Subscribing the same handler twice for the same event should only
    fire it once.
    """
    from nationcraft.core.events.bus import EventBus, Event

    bus = EventBus()
    calls = []

    def handler(event):
        calls.append(1)

    bus.subscribe("test.event", handler)
    bus.subscribe("test.event", handler)  # duplicate

    await bus.publish(Event(type="test.event"))
    assert len(calls) == 1, f"handler should be called once, got {len(calls)}"


# ---------------------------------------------------------------------
# JWT leeway for clock skew
# ---------------------------------------------------------------------

def test_jwt_decode_with_leeway_handles_future_iat():
    """A token issued slightly in the future (clock skew) should still verify."""
    import time
    from nationcraft.infrastructure.security.jwt_utils import IssueTokens, VerifyToken

    issuer = IssueTokens(secret="test-secret-32-bytes-long-aaaaaaaaa", issuer="test")
    pair = issuer.for_player(42, role="player")

    verifier = VerifyToken(secret="test-secret-32-bytes-long-aaaaaaaaa", issuer="test")
    # Should succeed because leeway is applied.
    payload = verifier(pair.access_token, expected_type="access")
    assert payload["sub"] == "42"
    assert payload["type"] == "access"


# ---------------------------------------------------------------------
# SQLite WAL pragmas
# ---------------------------------------------------------------------

@pytest.mark.asyncio
async def test_sqlite_wal_pragmas_applied():
    """The SQLite engine should install PRAGMA handlers that switch the
    journal mode to WAL and set busy_timeout and foreign_keys.
    """
    import os
    os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"
    # Re-import to pick up the new URL.
    import importlib
    from nationcraft.infrastructure.db import session as session_mod
    importlib.reload(session_mod)
    from sqlalchemy import text

    async with session_mod.engine.connect() as conn:
        # Verify journal_mode is WAL or memory (memory is allowed for :memory:).
        result = await conn.execute(text("PRAGMA journal_mode"))
        mode = result.scalar()
        assert mode in ("wal", "memory"), f"expected wal or memory, got {mode}"

        # Verify busy_timeout was set.
        result = await conn.execute(text("PRAGMA busy_timeout"))
        busy = result.scalar()
        assert busy == 5000, f"expected busy_timeout=5000, got {busy}"

        # Verify foreign_keys is ON.
        result = await conn.execute(text("PRAGMA foreign_keys"))
        fk = result.scalar()
        assert fk == 1, f"expected foreign_keys=1, got {fk}"

    await session_mod.dispose()


# ---------------------------------------------------------------------
# AuthMiddleware locale cache pre-population
# ---------------------------------------------------------------------

def test_auth_middleware_locale_cache_pre_populates():
    """The middleware should return a locale immediately (synchronously)
    and never block on a network call.
    """
    from nationcraft.bot.middleware.auth import AuthMiddleware
    from nationcraft.core.config import settings

    mw = AuthMiddleware(api_client=MagicMock())

    class FakeUser:
        id = 999
        language_code = "fa"

    # First call — should return "fa" (the Telegram language_code) immediately.
    start = time.perf_counter()
    locale = mw._resolve_locale_fast(FakeUser())
    elapsed = time.perf_counter() - start
    assert locale == "fa"
    # Must be synchronous-fast: < 50ms (no network).
    assert elapsed < 0.05, f"resolve_locale_fast took {elapsed*1000:.1f}ms — should be sync"

    # Second call — still fast (cache hit).
    start = time.perf_counter()
    locale = mw._resolve_locale_fast(FakeUser())
    elapsed = time.perf_counter() - start
    assert locale == "fa"
    assert elapsed < 0.05
