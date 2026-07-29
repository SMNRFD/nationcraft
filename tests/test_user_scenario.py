"""End-to-end simulation: reproduce the user's bug scenario and confirm
the fixes prevent it.

User's original report (paraphrased):
1. /panel — "must login first" (no token, fast)
2. /login — "send your password" (state set, fast)
3. password typed — bot calls API /auth/login — fast (5s timeout, not 15s)
4. /panel — bot calls /auth/me — fast (middleware uses cached locale,
   refresh runs in background)
5. Even if /auth/me times out, the bot doesn't block the next message
6. Even if the access token expires (15 min later), refresh transparently
   rotates it
"""
from __future__ import annotations

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock

import pytest


@pytest.mark.asyncio
async def test_full_login_flow_does_not_block_on_slow_api():
    """Simulate the user's exact scenario and verify the bot's handler
    chain returns quickly even when the API is slow.
    """
    from nationcraft.bot.api_client import ApiClient
    from nationcraft.core.exceptions import NationCraftError

    # Set up the API client with a fast-failing mock (simulates API that
    # would have hung for 15s under the old code).
    client = ApiClient(base_url="http://test")

    # Mock the HTTP layer to simulate a slow login (2s, well within the 5s
    # timeout but enough to expose any blocking issue).
    ok_resp = MagicMock()
    ok_resp.status_code = 200
    ok_resp.json.return_value = {
        "ok": True,
        "data": {
            "access_token": "tok-1",
            "refresh_token": "ref-1",
        },
    }

    async def _slow_login(method, url, headers=None, json=None, **kwargs):
        # Simulate a 1s API delay (well under the 5s timeout, but enough
        # to expose any blocking issue).
        await asyncio.sleep(1.0)
        return ok_resp

    mock_client = AsyncMock()
    mock_client.request = _slow_login
    mock_client.is_closed = False
    client._client = mock_client

    # Simulate: user types /login, then sends password.
    start = time.perf_counter()
    await client.login(telegram_id=42, password="password12345")
    elapsed = time.perf_counter() - start
    # Should be ~1s, not 15s.
    assert elapsed < 5.0, f"login took {elapsed:.2f}s — too long"
    assert client.get_token(42) == "tok-1"


@pytest.mark.asyncio
async def test_401_after_login_triggers_refresh_not_permanent_failure():
    """Reproduces the user's symptom: successful login, then /panel call
    fails with 401. With the fix, the refresh token rotates the access
    token and the request succeeds on retry.
    """
    from nationcraft.bot.api_client import ApiClient

    client = ApiClient(base_url="http://test")
    # Simulate the user logged in 30 minutes ago — access token has expired.
    client.set_tokens(
        telegram_id=42,
        access_token="expired-access-tok",
        refresh_token="valid-refresh-tok",
    )

    # The first call returns 401 (expired). The refresh succeeds. The retry
    # returns 200.
    refresh_resp = MagicMock()
    refresh_resp.status_code = 200
    refresh_resp.json.return_value = {
        "ok": True,
        "data": {"access_token": "new-access-tok", "refresh_token": "new-refresh-tok"},
    }
    ok_data = {"hello": "world"}
    ok_resp = MagicMock()
    ok_resp.status_code = 200
    ok_resp.json.return_value = {"ok": True, "data": ok_data}

    call_log = []

    async def _mock_request(method, url, headers=None, json=None, **kwargs):
        call_log.append((method, url))
        if "refresh" in url:
            return refresh_resp
        # First non-refresh call: 401 expired.
        if len([c for c in call_log if "refresh" not in c[1]]) == 1:
            unauth = MagicMock()
            unauth.status_code = 401
            unauth.json.return_value = {"ok": False, "error": {"code": "authentication_failed"}}
            return unauth
        # Retry after refresh: 200.
        return ok_resp

    mock_client = AsyncMock()
    mock_client.request = _mock_request
    mock_client.post = AsyncMock(return_value=refresh_resp)
    mock_client.is_closed = False
    client._client = mock_client

    result = await client.get_me(42)
    # Should have succeeded on retry.
    assert result == ok_data
    # The access token should now be the new one.
    assert client.get_token(42) == "new-access-tok"
    assert client.get_refresh_token(42) == "new-refresh-tok"


@pytest.mark.asyncio
async def test_locale_middleware_does_not_block_handler_chain():
    """The middleware should return a locale synchronously even on cache
    miss, so the handler chain never blocks on a slow /auth/me call.
    """
    from nationcraft.bot.middleware.auth import AuthMiddleware

    # Mock api_client where get_me takes 5s.
    slow_api = MagicMock()
    slow_api.get_token = MagicMock(return_value="fake-token")

    async def _slow_get_me(tid):
        await asyncio.sleep(5.0)  # Simulate a hung API
        return {"locale": "en"}

    slow_api.get_me = _slow_get_me

    mw = AuthMiddleware(api_client=slow_api)

    class FakeUser:
        id = 42
        language_code = "fa"

    # First call — synchronous, returns immediately.
    start = time.perf_counter()
    locale = mw._resolve_locale_fast(FakeUser())
    elapsed = time.perf_counter() - start
    assert elapsed < 0.05, f"resolve_locale_fast took {elapsed*1000:.1f}ms — should be sync"
    assert locale == "fa"

    # Trigger background refresh — should not block.
    start = time.perf_counter()
    mw._maybe_refresh_locale(42)
    elapsed = time.perf_counter() - start
    assert elapsed < 0.05, f"_maybe_refresh_locale took {elapsed*1000:.1f}ms — should be non-blocking"

    # Wait briefly for the background task to start (it's scheduled).
    await asyncio.sleep(0.05)
    # The refresh task should be in-flight.
    assert 42 in mw._refresh_tasks

    # Clean up: cancel the in-flight task.
    mw.invalidate_locale(42)
    await asyncio.sleep(0.05)
