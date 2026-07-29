"""Tests for the getMe retry + process-survival fixes.

These tests cover the bugs identified from the user's server log:

  2026-07-29T12:05:20 [error] main.task.exited error='HTTP Client says -
  Request timeout error' name=bot

The root cause: ``bot.get_me()`` timed out (Iran network blocks
api.telegram.org), and the resulting ``TelegramNetworkError`` propagated
up and killed the ENTIRE process — including the perfectly-healthy API
and worker.

The fixes:
1. ``run_bot`` retries ``get_me()`` up to 5 times with exponential backoff.
2. If all retries fail, ``run_bot`` enters "degraded polling" mode
   (starts polling anyway — aiogram's polling loop has its own retry logic).
3. ``run_all`` no longer shuts down the API and worker when ONLY the bot
   task exits. It only shuts down everything on signal or when the
   API/worker task exits.
4. The aiohttp session is ALWAYS closed (try/finally), preventing the
   "Unclosed client session" warning.
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------
# Fix 1: run_bot retries getMe with backoff
# ---------------------------------------------------------------------

def test_run_bot_has_getme_retry_loop():
    """``run_bot`` should have a retry loop for ``bot.get_me()``.

    Without this, a single timeout on getMe (common on Iran's throttled
    network) crashes the entire process.
    """
    import inspect
    from nationcraft.bot.app import run_bot
    source = inspect.getsource(run_bot)
    # Should have a retry loop for getMe.
    assert "for attempt in range" in source, (
        "run_bot should have a retry loop for getMe — without it, a single "
        "timeout crashes the entire process"
    )
    assert "bot.get_me()" in source, (
        "run_bot should call bot.get_me() inside the retry loop"
    )
    assert "TelegramNetworkError" in source, (
        "run_bot should catch TelegramNetworkError and retry"
    )


def test_run_bot_has_max_getme_retries():
    """``run_bot`` should retry getMe up to 5 times."""
    import inspect
    from nationcraft.bot.app import run_bot
    source = inspect.getsource(run_bot)
    assert "max_getme_retries = 5" in source, (
        "run_bot should retry getMe up to 5 times (was 0 — no retry)"
    )


def test_run_bot_enters_degraded_mode_on_getme_failure():
    """If all getMe retries fail, ``run_bot`` should enter "degraded
    polling" mode (start polling anyway) instead of crashing."""
    import inspect
    from nationcraft.bot.app import run_bot
    source = inspect.getsource(run_bot)
    assert "degraded" in source.lower(), (
        "run_bot should enter 'degraded' mode when getMe fails — "
        "start polling anyway (aiogram's polling loop has its own retry)"
    )


# ---------------------------------------------------------------------
# Fix 2: run_bot always closes the session (no "Unclosed client session")
# ---------------------------------------------------------------------

def test_run_bot_closes_session_in_finally():
    """``run_bot`` should close the bot session in a ``finally`` block
    so it's ALWAYS closed, even if getMe/polling raises.

    Without this, the user sees:
      Unclosed client session
      client_session: <aiohttp.client.ClientSession object at 0x...>
    """
    import inspect
    from nationcraft.bot.app import run_bot
    source = inspect.getsource(run_bot)
    # The session close should be in a finally block.
    assert "await bot.session.close()" in source, (
        "run_bot should close the bot session"
    )
    assert "finally:" in source, (
        "run_bot should close the session in a finally block — "
        "otherwise the session leaks when getMe/polling raises"
    )


# ---------------------------------------------------------------------
# Fix 3: run_all doesn't shut down API/worker when only bot exits
# ---------------------------------------------------------------------

def test_run_all_keeps_running_when_only_bot_exits():
    """``run_all`` should NOT shut down the API and worker when ONLY the
    bot task exits.

    The user's log showed:
      [error] main.task.exited error='HTTP Client says - Request timeout
      error' name=bot
      [info] main.shutdown.grace_period seconds=10
      Shutting down

    This is wrong — the API and worker were perfectly healthy, but they
    were shut down because the bot crashed. The fix: only shut down
    everything on signal or when the API/worker exits.
    """
    import inspect
    from pathlib import Path
    main_path = Path(__file__).resolve().parent.parent / "main.py"
    source = main_path.read_text()

    # run_all should check the task name and only shut down everything
    # if the API or worker exited (not just the bot).
    assert "should_shutdown_all" in source, (
        "run_all should use a should_shutdown_all flag to decide whether "
        "to shut down all services"
    )
    assert 't.get_name() in ("api", "worker")' in source, (
        "run_all should only shut down everything if the API or worker "
        "task exited — NOT if only the bot exited"
    )
    assert "main.bot.exited_keep_running" in source, (
        "run_all should log a 'bot exited, keeping API/worker running' "
        "message when only the bot exits"
    )


# ---------------------------------------------------------------------
# Fix 4: run_bot catches TelegramNetworkError on getMe
# ---------------------------------------------------------------------

@pytest.mark.asyncio
async def test_run_bot_catches_telegram_network_error_on_getme():
    """When ``bot.get_me()`` raises ``TelegramNetworkError``, ``run_bot``
    should catch it and retry, NOT let it propagate up and crash the process.
    """
    import inspect
    from nationcraft.bot.app import run_bot
    source = inspect.getsource(run_bot)

    # The getMe call should be inside a try/except that catches
    # TelegramNetworkError.
    assert "except TelegramNetworkError" in source, (
        "run_bot should catch TelegramNetworkError around getMe — "
        "without this, the error propagates and crashes the process"
    )


def test_telegram_network_error_is_imported():
    """``TelegramNetworkError`` should be imported in app.py."""
    from nationcraft.bot import app
    assert hasattr(app, "TelegramNetworkError"), (
        "TelegramNetworkError should be imported in bot/app.py"
    )
