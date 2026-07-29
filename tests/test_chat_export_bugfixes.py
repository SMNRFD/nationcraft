"""Tests for the critical bug fixes identified from the user's chat export.

These tests cover the specific bugs that caused the user's experience:
1. /login clearing the token unconditionally → 401 cascade on button clicks
2. Callback handlers making API calls without checking for token → 401
3. Local _safe_edit/_safe_answer not using the utils.py retry/timeout logic

The root cause was a RACE CONDITION:
  1. User logs in successfully → token stored.
  2. Bot's message.answer() blocks for 25s on Iran's throttled network.
  3. User (thinking the bot is broken) sends /login again → queued.
  4. Bot processes the queued /login → clear_token() evicts the VALID token.
  5. User's queued button clicks now run with NO token → 401 cascade.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------
# Bug 1: /login does NOT clear token if already logged in
# ---------------------------------------------------------------------

@pytest.mark.asyncio
async def test_login_does_not_clear_token_when_already_logged_in():
    """``cmd_login`` should NOT call ``clear_token`` if the user already
    has a token. Instead, it should show "already logged in".

    This is the ROOT CAUSE of the user's 401 cascade:
    - User logs in → token stored.
    - Bot's reply blocks for 25s (Iran network).
    - User sends /login again (queued) → clear_token() evicts the token.
    - User's button clicks → 401 (no token).

    The fix: /login checks for an existing token FIRST. If present,
    it shows "already logged in" and does NOT enter the password flow.
    """
    from nationcraft.bot.handlers.commands import cmd_login
    from nationcraft.bot.api_client import api_client

    message = MagicMock()
    message.from_user.id = 999111
    message.answer = AsyncMock()

    state = MagicMock()
    state.clear = AsyncMock()
    state.set_state = AsyncMock()

    # Simulate the user already having a token (from a previous login).
    api_client.set_tokens(999111, "existing-access-token", "existing-refresh-token")

    try:
        with patch("nationcraft.bot.handlers.commands.api_client", api_client):
            await cmd_login(message, state, locale="en")

        # Should NOT clear the token.
        assert api_client.get_token(999111) == "existing-access-token", (
            "cmd_login must NOT clear the token if the user is already logged in. "
            "This was the root cause of the 401 cascade."
        )
        # Should NOT enter the password flow.
        state.set_state.assert_not_called()
        # Should have shown "already logged in" message.
        assert message.answer.await_count >= 1
        answered_text = str(message.answer.await_args)
        assert "already" in answered_text.lower(), (
            f"expected 'already logged in' message, got: {answered_text}"
        )
    finally:
        api_client.clear_token(999111)


@pytest.mark.asyncio
async def test_login_clears_state_even_when_already_logged_in():
    """``cmd_login`` should clear the FSM state even if the user is
    already logged in (to exit any stale state from a previous flow)."""
    from nationcraft.bot.handlers.commands import cmd_login
    from nationcraft.bot.api_client import api_client

    message = MagicMock()
    message.from_user.id = 999222
    message.answer = AsyncMock()

    state = MagicMock()
    state.clear = AsyncMock()
    state.set_state = AsyncMock()

    api_client.set_tokens(999222, "tok", "ref")

    try:
        with patch("nationcraft.bot.handlers.commands.api_client", api_client):
            await cmd_login(message, state, locale="en")

        # State should be cleared (to exit any stale FSM state).
        state.clear.assert_awaited()
    finally:
        api_client.clear_token(999222)


@pytest.mark.asyncio
async def test_login_enters_password_flow_when_not_logged_in():
    """``cmd_login`` should enter the password flow (set FSM state) when
    the user does NOT have a token."""
    from nationcraft.bot.handlers.commands import cmd_login
    from nationcraft.bot.api_client import api_client
    from nationcraft.bot.handlers.states.auth import AuthStates

    message = MagicMock()
    message.from_user.id = 999333
    message.answer = AsyncMock()

    state = MagicMock()
    state.clear = AsyncMock()
    state.set_state = AsyncMock()

    # Ensure no token.
    api_client.clear_token(999333)

    with patch("nationcraft.bot.handlers.commands.api_client", api_client):
        await cmd_login(message, state, locale="en")

    # Should enter the password flow.
    state.set_state.assert_awaited_with(AuthStates.waiting_for_password)
    # Should have asked for password.
    assert message.answer.await_count >= 1


# ---------------------------------------------------------------------
# Bug 2: Callback handlers check for token before API calls
# ---------------------------------------------------------------------

@pytest.mark.asyncio
async def test_require_auth_returns_false_when_no_token():
    """``_require_auth`` should return False and show "please /login first"
    when the user has no token."""
    from nationcraft.bot.handlers.callbacks import _require_auth
    from nationcraft.bot.api_client import api_client

    cb = MagicMock()
    cb.from_user.id = 999444
    cb.message = MagicMock()

    # Ensure no token.
    api_client.clear_token(999444)

    result = await _require_auth(cb, locale="en")

    assert result is False, (
        "_require_auth should return False when the user has no token"
    )


@pytest.mark.asyncio
async def test_require_auth_returns_true_when_token_present():
    """``_require_auth`` should return True (and not show any message)
    when the user has a token."""
    from nationcraft.bot.handlers.callbacks import _require_auth
    from nationcraft.bot.api_client import api_client

    cb = MagicMock()
    cb.from_user.id = 999555
    cb.message = MagicMock()
    cb.answer = AsyncMock()

    api_client.set_tokens(999555, "tok", "ref")

    try:
        result = await _require_auth(cb, locale="en")

        assert result is True, (
            "_require_auth should return True when the user has a token"
        )
        # Should NOT have edited the message or answered the callback.
        cb.message.edit_text.assert_not_called()
        cb.answer.assert_not_called()
    finally:
        api_client.clear_token(999555)


# ---------------------------------------------------------------------
# Bug 3: Callbacks use utils.py safe_edit/safe_answer (not local versions)
# ---------------------------------------------------------------------

def test_callbacks_import_safe_edit_from_utils():
    """callbacks.py should import ``safe_edit`` and ``safe_answer`` from
    ``utils.py``, NOT define its own local versions.

    The local versions didn't have the retry/timeout cap logic, which
    meant they blocked for the full 15s session timeout on every network
    error. On Iran's throttled network, this caused each callback handler
    to take 15-30s, compounding into the reported 25-33s update durations.
    """
    import ast
    from pathlib import Path

    callbacks_path = (
        Path(__file__).resolve().parent.parent
        / "src" / "nationcraft" / "bot" / "handlers" / "callbacks.py"
    )
    source = callbacks_path.read_text()
    tree = ast.parse(source)

    # Check imports.
    imports_from_utils = False
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            if node.module and "utils" in node.module:
                for alias in node.names:
                    if alias.name in ("safe_edit", "safe_answer"):
                        imports_from_utils = True

    assert imports_from_utils, (
        "callbacks.py must import safe_edit/safe_answer from utils.py "
        "(the local versions don't have retry/timeout cap logic)"
    )

    # Check that callbacks.py does NOT define its own _safe_edit/_safe_answer.
    for node in ast.walk(tree):
        if isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef)):
            assert node.name not in ("_safe_edit", "_safe_answer"), (
                f"callbacks.py must NOT define its own {node.name} — "
                f"it should use the version from utils.py which has "
                f"retry/timeout cap logic"
            )


# ---------------------------------------------------------------------
# Bug 4: safe_send timeout is 8s (was 20s), retries is 1 (was 2)
# ---------------------------------------------------------------------

def test_safe_send_total_timeout_is_8s():
    """``_TOTAL_TIMEOUT_SECONDS`` should be 8.0 (was 20.0).

    20s was too long — on Iran's network, each blocked send took 10-30s,
    and a 20s cap meant each handler took up to 20s. 8s is short enough
    that the bot processes queued updates within a reasonable window.
    """
    from nationcraft.bot.utils import _TOTAL_TIMEOUT_SECONDS
    assert _TOTAL_TIMEOUT_SECONDS == 8.0, (
        f"expected 8.0, got {_TOTAL_TIMEOUT_SECONDS}"
    )


def test_safe_send_max_retries_is_1():
    """``_MAX_RETRIES`` should be 1 (was 2).

    2 retries (1 initial + 1 retry) added 5-10s of blocking on each
    network error. 1 (no retry) fails fast and lets the user retry
    by clicking the button again.
    """
    from nationcraft.bot.utils import _MAX_RETRIES
    assert _MAX_RETRIES == 1, (
        f"expected 1, got {_MAX_RETRIES}"
    )


# ---------------------------------------------------------------------
# Bug 5: TELEGRAM_REQUEST_TIMEOUT is 5s (was 15s)
# ---------------------------------------------------------------------

def test_telegram_request_timeout_is_5s():
    """The default ``TELEGRAM_REQUEST_TIMEOUT`` should be 5.0s (was 15.0s).

    15s was too long on Iran's throttled network — each blocked send
    took 10-15s, causing updates to queue up and compound. 5s fails
    fast enough that the bot can process queued updates.
    """
    from nationcraft.core.config import Settings
    s = Settings()
    assert s.TELEGRAM_REQUEST_TIMEOUT == 5.0, (
        f"expected 5.0, got {s.TELEGRAM_REQUEST_TIMEOUT}"
    )


# ---------------------------------------------------------------------
# Bug 6: register/login do NOT retry (avoid duplicate sessions)
# ---------------------------------------------------------------------

@pytest.mark.asyncio
async def test_register_does_not_retry_on_timeout():
    """``register()`` should NOT retry on timeout.

    On Iran's network, the event loop can be blocked by a slow Telegram
    send, causing httpx to raise ReadTimeout EVEN THOUGH the API
    successfully processed the request. Retrying creates DUPLICATE
    sessions at the API.
    """
    from nationcraft.bot.api_client import ApiClient
    from nationcraft.core.exceptions import NationCraftError

    client = ApiClient(base_url="http://test")
    call_count = {"n": 0}

    async def _mock_request(method, path, **kwargs):
        call_count["n"] += 1
        raise NationCraftError("timeout", code="api_timeout", status_code=504)

    client._request = _mock_request

    with pytest.raises(NationCraftError):
        await client.register(telegram_id=123, password="password123")

    assert call_count["n"] == 1, (
        f"register should NOT retry on timeout (creates duplicate sessions). "
        f"Got {call_count['n']} attempts."
    )


@pytest.mark.asyncio
async def test_login_does_not_retry_on_timeout():
    """``login()`` should NOT retry on timeout (same as register)."""
    from nationcraft.bot.api_client import ApiClient
    from nationcraft.core.exceptions import NationCraftError

    client = ApiClient(base_url="http://test")
    call_count = {"n": 0}

    async def _mock_request(method, path, **kwargs):
        call_count["n"] += 1
        raise NationCraftError("timeout", code="api_timeout", status_code=504)

    client._request = _mock_request

    with pytest.raises(NationCraftError):
        await client.login(telegram_id=123, password="password123")

    assert call_count["n"] == 1, (
        f"login should NOT retry on timeout (creates duplicate sessions). "
        f"Got {call_count['n']} attempts."
    )
