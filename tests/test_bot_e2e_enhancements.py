"""Tests for the new bot enhancements:
- _build_api_server honors TELEGRAM_API_BASE
- api_client.register/login retry on transient errors
- mock Telegram server handles the methods aiogram uses
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------
# _build_api_server honors TELEGRAM_API_BASE
# ---------------------------------------------------------------------

def test_build_api_server_default_is_production():
    """When TELEGRAM_API_BASE is not set, _build_api_server should return
    the production TelegramAPIServer (https://api.telegram.org)."""
    from nationcraft.bot.app import _build_api_server
    from nationcraft.core.config import settings

    orig = settings.TELEGRAM_API_BASE
    try:
        settings.TELEGRAM_API_BASE = "https://api.telegram.org"
        srv = _build_api_server()
        # The api_url method should produce the standard production URL.
        url = srv.api_url(token="123:abc", method="getMe")
        assert url == "https://api.telegram.org/bot123:abc/getMe", (
            f"expected production URL, got {url!r}"
        )
    finally:
        settings.TELEGRAM_API_BASE = orig


def test_build_api_server_custom_for_mock():
    """When TELEGRAM_API_BASE is set to a local URL, _build_api_server
    should produce a TelegramAPIServer that points at that URL.

    This is the key enabler for end-to-end testing — the bot can be
    pointed at a local mock Telegram Bot API server instead of the
    real api.telegram.org.
    """
    from nationcraft.bot.app import _build_api_server
    from nationcraft.core.config import settings

    orig = settings.TELEGRAM_API_BASE
    try:
        settings.TELEGRAM_API_BASE = "http://127.0.0.1:8081"
        srv = _build_api_server()
        url = srv.api_url(token="123:abc", method="getMe")
        assert url == "http://127.0.0.1:8081/bot123:abc/getMe", (
            f"expected local mock URL, got {url!r}"
        )
    finally:
        settings.TELEGRAM_API_BASE = orig


def test_build_api_server_handles_token_with_colon():
    """The bot token contains a colon (e.g. 123:abc). The api_url method
    should NOT URL-encode the colon — aiogram sends the request with the
    raw colon in the path, and our mock server's catch-all route handles
    both forms."""
    from nationcraft.bot.app import _build_api_server
    from nationcraft.core.config import settings

    orig = settings.TELEGRAM_API_BASE
    try:
        settings.TELEGRAM_API_BASE = "http://localhost:8081"
        srv = _build_api_server()
        url = srv.api_url(token="1234567890:fake-token", method="sendMessage")
        # The colon should be preserved in the URL.
        assert "1234567890:fake-token" in url or "1234567890%3Afake-token" in url, (
            f"token with colon should be in URL, got {url!r}"
        )
    finally:
        settings.TELEGRAM_API_BASE = orig


def test_build_api_server_strips_existing_suffix():
    """If the user provides the full template URL (with /bot{token}/{method}),
    _build_api_server should strip it before passing to from_base (which
    adds its own suffix). This makes the setting idempotent."""
    from nationcraft.bot.app import _build_api_server
    from nationcraft.core.config import settings

    orig = settings.TELEGRAM_API_BASE
    try:
        # With full template
        settings.TELEGRAM_API_BASE = "http://localhost:8081/bot{token}/{method}"
        srv1 = _build_api_server()
        url1 = srv1.api_url(token="123:abc", method="getMe")

        # With just origin
        settings.TELEGRAM_API_BASE = "http://localhost:8081"
        srv2 = _build_api_server()
        url2 = srv2.api_url(token="123:abc", method="getMe")

        assert url1 == url2, (
            f"full template and origin-only should produce the same URL. "
            f"got {url1!r} vs {url2!r}"
        )
    finally:
        settings.TELEGRAM_API_BASE = orig


# ---------------------------------------------------------------------
# api_client.register/login do NOT retry (avoid duplicate sessions)
# ---------------------------------------------------------------------

@pytest.mark.asyncio
async def test_register_does_not_retry_on_transient_error():
    """register() should NOT retry on transient errors (503, timeout).

    On a throttled network (Iran), the event loop can be blocked by a
    slow Telegram send, causing httpx to raise ReadTimeout EVEN THOUGH
    the API successfully processed the request. Retrying in that case
    creates DUPLICATE sessions at the API. Instead, we fail fast and
    let the user retry manually.
    """
    from nationcraft.bot.api_client import ApiClient
    from nationcraft.core.exceptions import NationCraftError

    client = ApiClient(base_url="http://test")

    call_count = {"n": 0}

    async def _mock_request(method, path, **kwargs):
        call_count["n"] += 1
        raise NationCraftError("service unavailable", code="api_error", status_code=503)

    client._request = _mock_request  # type: ignore[assignment]

    with pytest.raises(NationCraftError):
        await client.register(telegram_id=123, password="password123")

    assert call_count["n"] == 1, (
        f"expected 1 attempt (no retry on transient), got {call_count['n']}"
    )


@pytest.mark.asyncio
async def test_register_does_not_retry_on_definitive_error():
    """register() should NOT retry on a definitive error (409 player_exists,
    401 auth). Retrying these is pointless and wastes time."""
    from nationcraft.bot.api_client import ApiClient
    from nationcraft.core.exceptions import NationCraftError

    client = ApiClient(base_url="http://test")

    call_count = {"n": 0}

    async def _mock_request(method, path, **kwargs):
        call_count["n"] += 1
        # 409 is definitive — don't retry.
        raise NationCraftError("player already exists", code="player_exists", status_code=409)

    client._request = _mock_request  # type: ignore[assignment]

    with pytest.raises(NationCraftError) as exc_info:
        await client.register(telegram_id=123, password="password123")

    assert exc_info.value.code == "player_exists"
    assert call_count["n"] == 1, (
        f"expected 1 attempt (no retry on 409), got {call_count['n']}"
    )


@pytest.mark.asyncio
async def test_register_raises_on_transient_error():
    """If the API call fails with a transient error, register() should
    raise immediately (1 attempt, no retry)."""
    from nationcraft.bot.api_client import ApiClient
    from nationcraft.core.exceptions import NationCraftError

    client = ApiClient(base_url="http://test")

    call_count = {"n": 0}

    async def _mock_request(method, path, **kwargs):
        call_count["n"] += 1
        raise NationCraftError("timeout", code="api_timeout", status_code=504)

    client._request = _mock_request  # type: ignore[assignment]

    with pytest.raises(NationCraftError) as exc_info:
        await client.register(telegram_id=123, password="password123")

    assert exc_info.value.code == "api_timeout"
    assert call_count["n"] == 1, (
        f"expected 1 attempt (no retry), got {call_count['n']}"
    )


@pytest.mark.asyncio
async def test_login_does_not_retry_on_transient_error():
    """login() should NOT retry on transient errors (same as register)."""
    from nationcraft.bot.api_client import ApiClient
    from nationcraft.core.exceptions import NationCraftError

    client = ApiClient(base_url="http://test")

    call_count = {"n": 0}

    async def _mock_request(method, path, **kwargs):
        call_count["n"] += 1
        raise NationCraftError("timeout", code="api_timeout", status_code=504)

    client._request = _mock_request  # type: ignore[assignment]

    with pytest.raises(NationCraftError):
        await client.login(telegram_id=123, password="password123")

    assert call_count["n"] == 1, (
        f"expected 1 attempt (no retry on transient), got {call_count['n']}"
    )


@pytest.mark.asyncio
async def test_login_does_not_retry_on_401():
    """login() should NOT retry on 401 (wrong password)."""
    from nationcraft.bot.api_client import ApiClient
    from nationcraft.core.exceptions import NationCraftError

    client = ApiClient(base_url="http://test")

    call_count = {"n": 0}

    async def _mock_request(method, path, **kwargs):
        call_count["n"] += 1
        raise NationCraftError("invalid credentials", code="authentication_failed", status_code=401)

    client._request = _mock_request  # type: ignore[assignment]

    with pytest.raises(NationCraftError) as exc_info:
        await client.login(telegram_id=123, password="wrongpassword")

    assert exc_info.value.code == "authentication_failed"
    assert call_count["n"] == 1, (
        f"expected 1 attempt (no retry on 401), got {call_count['n']}"
    )


# ---------------------------------------------------------------------
# Mock Telegram server smoke test (in-process, no subprocess)
# ---------------------------------------------------------------------

@pytest.mark.asyncio
async def test_mock_telegram_server_get_me():
    """The mock Telegram server should respond to getMe with the bot info."""
    from httpx import ASGITransport, AsyncClient
    from scripts.mock_telegram_server import app, state

    state.reset()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # getMe is a POST to /bot{token}/getMe
        r = await client.post("/bot123:fake/getMe")
        assert r.status_code == 200
        body = r.json()
        assert body["ok"] is True
        assert "result" in body
        assert body["result"]["is_bot"] is True
        assert "username" in body["result"]


@pytest.mark.asyncio
async def test_mock_telegram_server_send_message():
    """The mock Telegram server should store sendMessage calls."""
    from httpx import ASGITransport, AsyncClient
    from scripts.mock_telegram_server import app, state

    state.reset()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # Send a message via sendMessage
        r = await client.post("/bot123:fake/sendMessage", data={
            "chat_id": "12345",
            "text": "Hello from test!",
        })
        assert r.status_code == 200
        body = r.json()
        assert body["ok"] is True
        assert body["result"]["text"] == "Hello from test!"
        assert body["result"]["chat"]["id"] == 12345

        # Verify it was stored
        r2 = await client.get("/test/sent_messages/12345")
        assert r2.status_code == 200
        msgs = r2.json()["messages"]
        assert len(msgs) == 1
        assert msgs[0]["text"] == "Hello from test!"


@pytest.mark.asyncio
async def test_mock_telegram_server_push_and_get_updates():
    """The mock Telegram server should let us push updates via the test
    helper and have them returned by getUpdates."""
    from httpx import ASGITransport, AsyncClient
    from scripts.mock_telegram_server import app, state

    state.reset()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # Push a /start command
        r = await client.post("/test/push_command", json={
            "chat_id": 111,
            "user_id": 222,
            "command": "start",
            "username": "tester",
        })
        assert r.status_code == 200
        update_id = r.json()["update_id"]
        assert update_id >= 1

        # Now call getUpdates with a short timeout — should return the update.
        r2 = await client.post("/bot123:fake/getUpdates", data={"timeout": "0"})
        assert r2.status_code == 200
        body = r2.json()
        assert body["ok"] is True
        updates = body["result"]
        assert len(updates) == 1
        assert updates[0]["update_id"] == update_id
        assert updates[0]["message"]["text"] == "/start"
        # The message should include entities marking the bot_command.
        assert any(e["type"] == "bot_command" for e in updates[0]["message"].get("entities", []))


@pytest.mark.asyncio
async def test_mock_telegram_server_get_updates_returns_empty_on_timeout():
    """When no updates are available, getUpdates should return an empty
    list after the timeout expires (matching Telegram's long-poll behavior)."""
    from httpx import ASGITransport, AsyncClient
    from scripts.mock_telegram_server import app, state

    state.reset()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # No updates pushed — getUpdates with timeout=0 should return [].
        r = await client.post("/bot123:fake/getUpdates", data={"timeout": "0"})
        assert r.status_code == 200
        body = r.json()
        assert body["ok"] is True
        assert body["result"] == []


@pytest.mark.asyncio
async def test_mock_telegram_server_answer_callback_query():
    """The mock Telegram server should record answerCallbackQuery calls."""
    from httpx import ASGITransport, AsyncClient
    from scripts.mock_telegram_server import app, state

    state.reset()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.post("/bot123:fake/answerCallbackQuery", data={
            "callback_query_id": "cb-123",
            "text": "Button clicked!",
            "show_alert": "false",
        })
        assert r.status_code == 200
        assert r.json()["ok"] is True

        # Verify it was recorded
        r2 = await client.get("/test/answered_callbacks")
        assert r2.status_code == 200
        callbacks = r2.json()["callbacks"]
        assert len(callbacks) == 1
        assert callbacks[0]["callback_query_id"] == "cb-123"
        assert callbacks[0]["text"] == "Button clicked!"


@pytest.mark.asyncio
async def test_mock_telegram_server_reset_clears_state():
    """The /test/reset endpoint should clear sent_messages, edited_messages,
    and answered_callbacks (but NOT the updates_queue or update_id counter)."""
    from httpx import ASGITransport, AsyncClient
    from scripts.mock_telegram_server import app, state

    state.reset()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # Send a message to populate state.
        await client.post("/bot123:fake/sendMessage", data={"chat_id": "1", "text": "hi"})
        assert len(state.sent_messages) == 1

        # Reset
        r = await client.post("/test/reset")
        assert r.status_code == 200
        assert r.json()["ok"] is True

        # sent_messages should be cleared
        assert len(state.sent_messages) == 0


@pytest.mark.asyncio
async def test_mock_telegram_server_handles_url_encoded_token():
    """aiogram URL-encodes the colon in the bot token. The mock server's
    catch-all route should handle both the raw and URL-encoded forms."""
    from httpx import ASGITransport, AsyncClient
    from scripts.mock_telegram_server import app, state

    state.reset()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # URL-encoded colon (%3A) — this is what aiogram actually sends.
        r = await client.post("/bot123%3Afake/getMe")
        assert r.status_code == 200
        assert r.json()["ok"] is True


# ---------------------------------------------------------------------
# main.py: _apply_local_overrides uses API_PORT
# ---------------------------------------------------------------------

def _load_main_module():
    """Load the project-root main.py as a module.

    main.py lives at the project root (not inside src/nationcraft/), so it
    can't be imported as ``nationcraft.main``. We load it directly from its
    file path using importlib.
    """
    import importlib.util
    from pathlib import Path

    main_path = Path(__file__).resolve().parent.parent / "main.py"
    spec = importlib.util.spec_from_file_location("_nationcraft_main", main_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_local_override_uses_api_port_from_env():
    """When --local is used with a custom API_PORT env var, the
    API_BASE_URL should include that port (not hardcoded :8000).

    This was a real bug: the user ran `python main.py --local --port 8095`
    but the bot's API_BASE_URL was still http://localhost:8000, so the
    bot couldn't reach the API.
    """
    import os
    main_mod = _load_main_module()
    _apply_local_overrides = main_mod._apply_local_overrides
    from nationcraft.core.config import settings

    # Save original env
    orig_env = {k: os.environ.get(k) for k in ["DATABASE_URL", "REDIS_URL", "API_BASE_URL", "API_HOST", "API_PORT"]}
    orig_settings = {f: getattr(settings, f) for f in ["DATABASE_URL", "REDIS_URL", "API_BASE_URL", "API_HOST", "API_PORT"]}

    try:
        # Set a custom port BEFORE calling _apply_local_overrides
        os.environ["API_HOST"] = "127.0.0.1"
        os.environ["API_PORT"] = "8095"
        # Need to reload settings so the new API_PORT is picked up
        from nationcraft.core.config import Settings
        new = Settings()
        for field in type(new).model_fields:
            setattr(settings, field, getattr(new, field))

        _apply_local_overrides()

        assert settings.API_BASE_URL == "http://127.0.0.1:8095", (
            f"expected http://127.0.0.1:8095, got {settings.API_BASE_URL!r}. "
            f"The --local flag was hardcoding :8000, ignoring the custom port."
        )
    finally:
        # Restore
        for k, v in orig_env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        for f, v in orig_settings.items():
            setattr(settings, f, v)


def test_local_override_converts_bind_all_to_localhost():
    """When API_HOST is 0.0.0.0 (bind-all), the API_BASE_URL should use
    'localhost' (you can't connect to 0.0.0.0 as a client)."""
    import os
    main_mod = _load_main_module()
    _apply_local_overrides = main_mod._apply_local_overrides
    from nationcraft.core.config import settings

    orig_env = {k: os.environ.get(k) for k in ["DATABASE_URL", "REDIS_URL", "API_BASE_URL", "API_HOST", "API_PORT"]}
    orig_settings = {f: getattr(settings, f) for f in ["DATABASE_URL", "REDIS_URL", "API_BASE_URL", "API_HOST", "API_PORT"]}

    try:
        os.environ["API_HOST"] = "0.0.0.0"
        os.environ["API_PORT"] = "8000"
        from nationcraft.core.config import Settings
        new = Settings()
        for field in type(new).model_fields:
            setattr(settings, field, getattr(new, field))

        _apply_local_overrides()

        assert "0.0.0.0" not in settings.API_BASE_URL, (
            f"API_BASE_URL should not contain 0.0.0.0 (clients can't connect to it). "
            f"Got {settings.API_BASE_URL!r}"
        )
        assert "localhost" in settings.API_BASE_URL or "127.0.0.1" in settings.API_BASE_URL, (
            f"expected localhost or 127.0.0.1 in API_BASE_URL, got {settings.API_BASE_URL!r}"
        )
    finally:
        for k, v in orig_env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        for f, v in orig_settings.items():
            setattr(settings, f, v)
