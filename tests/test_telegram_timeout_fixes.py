"""Tests for the Telegram bot timeout fixes (Bugs 31-35).

These tests cover the specific symptoms reported by the user:

- Update durations of 19-38s on a slow Iranian network, caused by
  ``safe_send`` retrying 3 times with 6s of sleep (1+2+3=6s) on top
  of each ~5-10s Telegram API call. The new ``safe_send`` caps total
  time at 20s and reduces to 2 retries with 1s sleep.

- ``api_timeout`` errors when the API actually responded fast (e.g.
  409 player_exists in 10ms). The previous global 15s read timeout
  blocked the bot's per-chat dispatcher for 15s on every hung call,
  which queued all subsequent updates. The new default is 8s, with
  12s for auth endpoints (Argon2).

- ``/status`` creating a new ``httpx.AsyncClient`` per call (resource
  leak + can't use the in-process fast path). Now uses
  ``api_client.health()`` which short-circuits to checking the
  uvicorn server state when the bot and API share one event loop.

- In-process fast path: when running ``--local``, the bot and API
  share one asyncio loop. The bot can check ``_api_server.should_exit``
  directly instead of round-tripping through HTTP, avoiding the
  deadlock where the bot blocks the loop with a slow Telegram send
  and the API can't answer the bot's HTTP call until the loop is free.
"""
from __future__ import annotations

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------
# Bug 31: safe_send total time is bounded
# ---------------------------------------------------------------------

@pytest.mark.asyncio
@pytest.mark.timeout(120)  # aiogram import overhead is ~10s on first test
async def test_safe_send_total_time_is_bounded():
    """``safe_send`` must not spend more than ~20s total, even on a
    flaky network that fails every attempt.

    Previously ``safe_send`` retried 3 times with 1+2+3=6s of sleep
    plus 3 × 5-10s Telegram API calls = up to 36s per failed send.
    On a slow Iranian network this caused the reported 19-38s update
    durations and made updates pile up.
    """
    from aiogram.exceptions import TelegramNetworkError
    from nationcraft.bot.utils import safe_send

    message = MagicMock()

    # Simulate Telegram always failing with a network error.
    async def _always_fail(*args, **kwargs):
        raise TelegramNetworkError(method=MagicMock(), message="WinError 10054")

    message.answer = _always_fail

    start = time.monotonic()
    result = await safe_send(message, "hello", parse_mode="Markdown")
    elapsed = time.monotonic() - start

    # Should return None (all retries failed).
    assert result is None
    # Should NOT take more than ~22s (20s cap + a small buffer for
    # the 1s sleep + overhead). The old behavior could take 30-36s.
    assert elapsed < 22.0, (
        f"safe_send took {elapsed:.1f}s — should be bounded to ~20s. "
        f"The old 3-retry × 6s-sleep behavior could take 30-36s."
    )


@pytest.mark.asyncio
async def test_safe_send_succeeds_first_try_is_fast():
    """If the first attempt succeeds, ``safe_send`` returns immediately
    without any sleep or retry."""
    from nationcraft.bot.utils import safe_send

    message = MagicMock()
    call_count = {"n": 0}

    async def _answer(*args, **kwargs):
        call_count["n"] += 1
        return MagicMock()

    message.answer = _answer

    start = time.monotonic()
    await safe_send(message, "hello", parse_mode="Markdown")
    elapsed = time.monotonic() - start

    assert call_count["n"] == 1
    assert elapsed < 1.0, (
        f"first-try success should take <1s, took {elapsed:.2f}s"
    )


@pytest.mark.asyncio
async def test_safe_send_retries_at_most_twice():
    """``safe_send`` should retry at most 2 times (1 initial + 1 retry)
    on network errors, not 3 times.

    Combined with the 1s sleep between retries, the worst case is
    ~2 × Telegram-API-call + 1s sleep, well under the 20s total cap.
    """
    from aiogram.exceptions import TelegramNetworkError
    from nationcraft.bot.utils import safe_send

    message = MagicMock()
    call_count = {"n": 0}

    async def _fail_twice_then_succeed(*args, **kwargs):
        call_count["n"] += 1
        if call_count["n"] < 3:
            raise TelegramNetworkError(method=MagicMock(), message="reset")
        return MagicMock()

    message.answer = _fail_twice_then_succeed

    await safe_send(message, "hello", parse_mode="Markdown")

    # Should have been called exactly 2 times (1 initial + 1 retry).
    # The third call should never happen — we only retry once.
    # Wait — actually if the first two fail and max_retries=2, we
    # give up after the 2nd failure. Let me re-check the semantics:
    # max_retries=2 means we attempt at most 2 times total. So if
    # both fail, we return None without a 3rd attempt.
    assert call_count["n"] == 2, (
        f"expected 2 attempts (1 initial + 1 retry), got {call_count['n']}"
    )


# ---------------------------------------------------------------------
# Bug 32: api_client has per-call timeouts (8s default, 12s auth)
# ---------------------------------------------------------------------

def test_api_client_default_timeout_is_8s():
    """The default API client timeout should be 8s (was 15s).

    15s blocked the bot's per-chat dispatcher too long when the API
    was genuinely broken, causing updates to queue and compound. 8s
    is enough for any legitimate fast API call (DB read + JSON
    serialize) while letting the bot recover quickly.
    """
    from nationcraft.bot.api_client import _DEFAULT_TIMEOUT
    assert _DEFAULT_TIMEOUT.read == pytest.approx(8.0)


def test_api_client_auth_timeout_is_12s():
    """Auth endpoints (register/login) should use a 12s timeout.

    Argon2 with RFC 9106 parameters (64 MiB memory, 3 iterations,
    2 parallelism) can take 1-2s on a slow machine under load. We'd
    rather wait than tell the user "timeout" when the operation is
    actually succeeding.
    """
    from nationcraft.bot.api_client import _AUTH_TIMEOUT
    assert _AUTH_TIMEOUT.read == pytest.approx(12.0)


@pytest.mark.asyncio
async def test_register_uses_auth_timeout():
    """``ApiClient.register`` should pass ``_AUTH_TIMEOUT`` to
    ``_request`` so Argon2-heavy register calls don't time out."""
    from nationcraft.bot.api_client import ApiClient, _AUTH_TIMEOUT

    client = ApiClient(base_url="http://test")

    # Mock _request to capture the timeout argument.
    captured: dict = {}

    async def _mock_request(method, path, **kwargs):
        captured["timeout"] = kwargs.get("timeout")
        return {"access_token": "tok", "refresh_token": "ref"}

    client._request = _mock_request  # type: ignore[assignment]

    await client.register(telegram_id=123, password="password123")

    assert captured["timeout"] is _AUTH_TIMEOUT, (
        f"register should pass _AUTH_TIMEOUT, got {captured.get('timeout')!r}"
    )


@pytest.mark.asyncio
async def test_login_uses_auth_timeout():
    """``ApiClient.login`` should also pass ``_AUTH_TIMEOUT``."""
    from nationcraft.bot.api_client import ApiClient, _AUTH_TIMEOUT

    client = ApiClient(base_url="http://test")

    captured: dict = {}

    async def _mock_request(method, path, **kwargs):
        captured["timeout"] = kwargs.get("timeout")
        return {"access_token": "tok", "refresh_token": "ref"}

    client._request = _mock_request  # type: ignore[assignment]

    await client.login(telegram_id=123, password="password123")

    assert captured["timeout"] is _AUTH_TIMEOUT, (
        f"login should pass _AUTH_TIMEOUT, got {captured.get('timeout')!r}"
    )


# ---------------------------------------------------------------------
# Bug 33: api_client.health() uses in-process fast path
# ---------------------------------------------------------------------

@pytest.mark.asyncio
async def test_health_uses_in_process_fast_path():
    """When ``_in_process_api`` is True, ``api_client.health()`` should
    return immediately with ``status='ok'`` WITHOUT making any HTTP
    call, by checking the ``is_serving`` callable set by main.run_all.

    This avoids the deadlock where the bot blocks the event loop
    with a slow Telegram send, and the HTTP call to /health can't
    be answered by the API until the loop is free.
    """
    from nationcraft.bot.api_client import ApiClient, set_in_process_api

    client = ApiClient(base_url="http://test")

    # Mock the httpx client to fail if anything tries to use it.
    mock_http = AsyncMock()
    mock_http.get = AsyncMock(
        side_effect=AssertionError("should NOT make HTTP call when in-process")
    )
    client._client = mock_http

    # Enable in-process mode with a callable that says "API is serving".
    set_in_process_api(True, is_serving=lambda: True)
    try:
        result = await client.health()

        assert result["status"] == "ok"
        assert result["source"] == "in-process"
        # Verify no HTTP call was made.
        mock_http.get.assert_not_called()
    finally:
        set_in_process_api(False, is_serving=None)


@pytest.mark.asyncio
async def test_health_in_process_detects_shutting_down():
    """When the ``is_serving`` callable returns False (e.g. server is
    shutting down), the in-process fast path should fall through to
    HTTP (the API is no longer reliably serving)."""
    from nationcraft.bot.api_client import ApiClient, set_in_process_api

    client = ApiClient(base_url="http://test")

    # is_serving returns False (server shutting down).
    set_in_process_api(True, is_serving=lambda: False)
    try:
        # Mock HTTP to return a 503 (server shutting down).
        mock_resp = MagicMock()
        mock_resp.status_code = 503
        mock_http = MagicMock()
        mock_http.is_closed = False
        mock_http.get = AsyncMock(return_value=mock_resp)
        client._client = mock_http

        result = await client.health()

        assert result["status"] == "http_503"
        assert result["source"] == "http"
    finally:
        set_in_process_api(False, is_serving=None)


@pytest.mark.asyncio
async def test_health_http_fallback_on_unreachable():
    """When NOT in-process mode and the HTTP call fails, ``health()``
    should return a structured error, not raise."""
    from nationcraft.bot.api_client import ApiClient, set_in_process_api
    import httpx

    client = ApiClient(base_url="http://test")

    set_in_process_api(False, is_serving=None)

    # Mock httpx to raise ConnectError.
    mock_http = MagicMock()
    mock_http.is_closed = False
    mock_http.get = AsyncMock(side_effect=httpx.ConnectError("refused"))
    client._client = mock_http

    result = await client.health()

    assert result["status"] == "unreachable"
    assert result["source"] == "http"


# ---------------------------------------------------------------------
# Bug 34: set_in_process_api is called by run_all
# ---------------------------------------------------------------------

def test_run_all_sets_in_process_api():
    """``main.run_all`` should call ``set_in_process_api(True, ...)``
    so the bot's api_client can short-circuit HTTP when sharing one
    event loop with the API server."""
    from pathlib import Path
    main_path = Path(__file__).parent.parent / "main.py"
    source = main_path.read_text()
    assert "set_in_process_api(True" in source, (
        "run_all should call set_in_process_api(True, is_serving=...) to "
        "enable the in-process fast path for /health checks"
    )
    # Should also pass an is_serving callable so the fast path can
    # tell when the API is up vs shutting down.
    assert "is_serving=_is_api_serving" in source, (
        "run_all should pass an is_serving callable so health() can "
        "tell when the API is up vs shutting down"
    )


# ---------------------------------------------------------------------
# Bug 35: 409 player_exists surfaces correctly to the bot
# ---------------------------------------------------------------------

@pytest.mark.asyncio
async def test_register_409_player_exists_surfaces_correctly():
    """When the API returns 409 with ``code='player_exists'``, the
    bot's api_client should raise ``NationCraftError(code='player_exists')``
    (NOT ``api_timeout``), so the bot can show "already registered"
    instead of a misleading timeout message."""
    from unittest.mock import AsyncMock, MagicMock
    from nationcraft.bot.api_client import ApiClient
    from nationcraft.core.exceptions import NationCraftError

    client = ApiClient(base_url="http://test")

    # Mock httpx to return 409 with the player_exists error body.
    mock_resp = MagicMock()
    mock_resp.status_code = 409
    mock_resp.json.return_value = {
        "ok": False,
        "data": None,
        "error": {"code": "player_exists", "message": "player already exists"},
    }
    mock_client = AsyncMock()
    mock_client.request = AsyncMock(return_value=mock_resp)
    mock_client.is_closed = False
    client._client = mock_client

    with pytest.raises(NationCraftError) as exc_info:
        await client.register(telegram_id=123, password="password123")

    err = exc_info.value
    assert err.code == "player_exists", (
        f"expected code='player_exists', got code={err.code!r}. "
        f"The bot's process_register handler checks `exc.code == 'player_exists'` "
        f"to show 'already registered' — if this fails, the user sees a "
        f"misleading 'api_timeout' or generic error instead."
    )
    assert err.status_code == 409


@pytest.mark.asyncio
async def test_api_client_distinguishes_409_from_504():
    """A 409 Conflict (player exists) must NOT be misclassified as a
    504 timeout. The bot's error handler depends on the correct code
    to decide whether to clear the FSM state (409 = definitive, clear
    state) or keep it (504 = transient, let user retry)."""
    from unittest.mock import AsyncMock, MagicMock
    from nationcraft.bot.api_client import ApiClient
    from nationcraft.core.exceptions import NationCraftError, is_transient_error

    client = ApiClient(base_url="http://test")

    # 409 with player_exists error.
    mock_resp = MagicMock()
    mock_resp.status_code = 409
    mock_resp.json.return_value = {
        "ok": False, "data": None,
        "error": {"code": "player_exists", "message": "player already exists"},
    }
    mock_client = AsyncMock()
    mock_client.request = AsyncMock(return_value=mock_resp)
    mock_client.is_closed = False
    client._client = mock_client

    with pytest.raises(NationCraftError) as exc_info:
        await client._request("POST", "/auth/register", json={})

    err = exc_info.value
    # 409 is NOT transient — the bot should clear state and tell the
    # user to /login.
    assert not is_transient_error(err), (
        "409 player_exists must NOT be classified as transient — "
        "the bot should clear the FSM state and tell the user to /login"
    )
    assert err.code == "player_exists"
    assert err.status_code == 409


# ---------------------------------------------------------------------
# Bug 36: process_register shows "already_registered" on 409
# ---------------------------------------------------------------------

@pytest.mark.asyncio
async def test_process_register_shows_already_registered_on_409():
    """When /auth/register returns 409 player_exists, the bot's
    ``process_register`` handler should show "already registered"
    and clear the FSM state, NOT show a timeout/unreachable message.

    This is the user-facing fix for the reported symptom:
    > ⚠️ Cannot reach the game server. Error: api_timeout
    when the API actually responded with 409 in 10ms.
    """
    from nationcraft.bot.handlers.commands import process_register
    from nationcraft.core.exceptions import NationCraftError

    # Build a fake message + state.
    message = MagicMock()
    message.text = "password123"
    message.from_user.id = 123
    message.from_user.username = "tester"
    message.from_user.full_name = "Test User"
    message.answer = AsyncMock()

    state = MagicMock()
    state.clear = AsyncMock()

    # Patch api_client.register to raise player_exists.
    with patch(
        "nationcraft.bot.handlers.commands.api_client"
    ) as mock_api:
        mock_api.register = AsyncMock(
            side_effect=NationCraftError(
                "player already exists",
                code="player_exists",
                status_code=409,
            )
        )
        mock_api.get_token = MagicMock(return_value=None)

        # Use the real handler. We need to set the locale="en" default.
        # aiogram passes locale via middleware — in tests we pass it directly.
        await process_register(message, state, locale="en")

    # Should clear state (user is already registered, must /login).
    state.clear.assert_awaited()
    # Should have answered with "already registered" message.
    assert message.answer.await_count >= 1
    # The text should mention "already" — matching auth.already_registered.
    # We check the call args loosely because the i18n key may resolve to
    # a slightly different message.
    answered_text = str(message.answer.await_args)
    assert "already" in answered_text.lower() or "register" in answered_text.lower(), (
        f"expected 'already registered' message, got: {answered_text}"
    )


# ---------------------------------------------------------------------
# Bug 37: safe_send doesn't retry on TelegramBadRequest (non-parse)
# ---------------------------------------------------------------------

@pytest.mark.asyncio
async def test_safe_send_no_retry_on_non_parse_bad_request():
    """``safe_send`` should NOT retry on ``TelegramBadRequest`` errors
    that are NOT Markdown parse errors (e.g. "chat not found", "too
    long"). Retrying these is pointless and wastes time."""
    from aiogram.exceptions import TelegramBadRequest
    from nationcraft.bot.utils import safe_send

    message = MagicMock()
    call_count = {"n": 0}

    async def _always_bad_request(*args, **kwargs):
        call_count["n"] += 1
        raise TelegramBadRequest(
            method=MagicMock(),
            message="Bad Request: chat not found",
        )

    message.answer = _always_bad_request

    result = await safe_send(message, "hello", parse_mode="Markdown")
    assert result is None
    # Should be called exactly once — no retry on non-parse BadRequest.
    assert call_count["n"] == 1, (
        f"expected 1 call (no retry on non-parse BadRequest), got {call_count['n']}"
    )


# ---------------------------------------------------------------------
# Bug 38: safe_send re-raises CancelledError
# ---------------------------------------------------------------------

@pytest.mark.asyncio
async def test_safe_send_reraises_cancelled_error():
    """``safe_send`` should re-raise ``asyncio.CancelledError`` so the
    shutdown handler can clean up properly. Swallowing it would make
    the bot unresponsive to Ctrl+C."""
    from nationcraft.bot.utils import safe_send

    message = MagicMock()

    async def _cancel(*args, **kwargs):
        raise asyncio.CancelledError()

    message.answer = _cancel

    with pytest.raises(asyncio.CancelledError):
        await safe_send(message, "hello", parse_mode="Markdown")
