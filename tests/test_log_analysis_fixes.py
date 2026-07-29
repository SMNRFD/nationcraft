"""Tests for the log-analysis fixes (Bugs 24-27).

Covers:
- Bot default parse_mode is None (not MARKDOWN) — prevents
  TelegramBadRequest on user-supplied content
- API client timeout is 15s (not 5s) — prevents ReadTimeout on Argon2
- SQLAlchemy engine echo is False — prevents log spam
- Pre-flight API check retries for up to 30s (not single 5s check)
"""
from __future__ import annotations

import pytest


# ---------------------------------------------------------------------
# Bug 24: Pre-flight API check raced with API startup — REMOVED entirely
# ---------------------------------------------------------------------

def test_bot_has_no_pre_flight_api_check():
    """The pre-flight LOCAL API check was REMOVED because on Windows the
    ProactorEventLoop stalls localhost TCP connections, so the /health
    check timed out even when the API was running fine. The bot's
    error handlers already catch API errors gracefully.

    NOTE: This test specifically checks for the LOCAL API /health
    pre-flight check, NOT the getMe retry loop. The getMe retry loop
    (added later) is for reaching api.telegram.org, which is a
    completely different concern — it prevents the bot from crashing
    the entire process when Telegram is unreachable (Iran network).
    """
    import inspect
    from nationcraft.bot.app import run_bot
    source = inspect.getsource(run_bot)
    # The LOCAL API /health pre-flight check should NOT be present.
    # (The getMe retry loop is OK — it's for Telegram, not the local API.)
    assert "/health" not in source, (
        "run_bot should NOT have a pre-flight LOCAL API /health check — it "
        "causes 30s delays and false 'unreachable' warnings on Windows"
    )
    assert "api_client.health()" not in source, (
        "run_bot should NOT call api_client.health() as a pre-flight check"
    )


def test_windows_event_loop_fix():
    """On Windows, the SelectorEventLoop policy should be set to fix
    TCP stalls between aiohttp (Telegram), httpx (API client), and
    uvicorn (API server) sharing one event loop.
    """
    from pathlib import Path
    main_path = Path(__file__).parent.parent / "main.py"
    source = main_path.read_text()
    assert "WindowsSelectorEventLoopPolicy" in source, (
        "main.py should set WindowsSelectorEventLoopPolicy on Windows "
        "to fix ProactorEventLoop TCP stall issues"
    )


# ---------------------------------------------------------------------
# Bug 25: Bot default parse_mode=MARKDOWN caused TelegramBadRequest
# ---------------------------------------------------------------------

def test_bot_default_parse_mode_is_none():
    """The bot's default parse_mode should be None (plain text), NOT
    Markdown. Individual handlers that need Markdown explicitly pass
    parse_mode='Markdown' through safe_send().
    """
    import inspect
    from nationcraft.bot.app import run_bot
    source = inspect.getsource(run_bot)
    # Should use parse_mode=None, NOT ParseMode.MARKDOWN.
    assert "parse_mode=None" in source, (
        "bot default parse_mode should be None (plain text) to avoid "
        "TelegramBadRequest on user-supplied content with _ or *"
    )
    assert "ParseMode.MARKDOWN" not in source, (
        "bot should NOT use ParseMode.MARKDOWN as default — it causes "
        "TelegramBadRequest when usernames contain _ or *"
    )


# ---------------------------------------------------------------------
# Bug 26: httpx.ReadTimeout — 5s timeout too short for Argon2
# ---------------------------------------------------------------------

def test_api_client_timeout_is_bounded():
    """The API client read timeout should be bounded to ~8s for regular
    calls and ~8s for auth (Argon2) calls.

    Previously 5s was too short (Argon2 + DB I/O could exceed 5s on
    slow Windows, causing spurious ``httpx.ReadTimeout``).

    Then it was raised to 15s, which caused a different failure mode:
    every hung API call blocked the bot's per-chat dispatcher for
    15s, queuing all subsequent updates for that chat. On a slow
    Iranian network the queued updates compounded, producing the
    reported 19-38s update durations.

    The current behavior:
    - Default read timeout: 8s (covers Argon2 ~500ms + DB I/O ~2s +
      event-bus publish with comfortable margin; lets the bot
      recover quickly when the API is genuinely broken).
    - Auth (register/login) read timeout: 8s (was 12s — reduced to
      fail fast on throttled networks; 8s is still plenty for Argon2).
    """
    from nationcraft.bot.api_client import _DEFAULT_TIMEOUT, _AUTH_TIMEOUT
    assert _DEFAULT_TIMEOUT.read == pytest.approx(8.0), (
        f"expected default read timeout=8.0s, got {_DEFAULT_TIMEOUT.read}s"
    )
    assert _AUTH_TIMEOUT.read == pytest.approx(8.0), (
        f"expected auth read timeout=8.0s, got {_AUTH_TIMEOUT.read}s"
    )


# ---------------------------------------------------------------------
# Bug 27: SQLAlchemy echo=True spammed logs
# ---------------------------------------------------------------------

def test_sqlalchemy_echo_is_disabled():
    """The SQLAlchemy engine should have echo=False to prevent
    thousands of log lines per tick. Previously echo=settings.is_dev
    produced 100+ lines per tick (14 countries × multiple queries).
    """
    # Read the source file directly (avoids importing the module
    # which would try to build the engine and fail without DATABASE_URL).
    from pathlib import Path
    session_path = Path(__file__).parent.parent / "src" / "nationcraft" / "infrastructure" / "db" / "session.py"
    source = session_path.read_text()
    # The code line should be: kwargs: dict = {"echo": False}
    # (NOT: kwargs: dict = {"echo": settings.is_dev})
    assert '"echo": False' in source, (
        "engine should set echo=False to prevent log spam"
    )
    # The old code should NOT be present (excluding comments).
    # Check that no line of actual code (not starting with #) has
    # echo=settings.is_dev or "echo": settings.is_dev.
    for line in source.split("\n"):
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        if 'echo": settings.is_dev' in stripped or "echo=settings.is_dev" in stripped:
            pytest.fail(
                f"line still uses echo=settings.is_dev (causes log spam): {stripped}"
            )


# ---------------------------------------------------------------------
# Bot utils: escape_md handles all special chars
# ---------------------------------------------------------------------

def test_escape_md_all_special_chars():
    """escape_md should escape all Telegram Markdown V1 special chars."""
    from nationcraft.bot.utils import escape_md
    # All special chars: _ * ` [ ]
    assert escape_md("_") == r"\_"
    assert escape_md("*") == r"\*"
    assert escape_md("`") == r"\`"
    assert escape_md("[") == r"\["
    assert escape_md("]") == r"\]"
    # Combined
    assert escape_md("YSN_RFD") == r"YSN\_RFD"
    assert escape_md("hello *world*") == r"hello \*world\*"


def test_safe_send_falls_back_on_markdown_error():
    """safe_send should retry as plain text if Markdown parse fails."""
    import asyncio
    from unittest.mock import AsyncMock, MagicMock
    from aiogram.exceptions import TelegramBadRequest
    from nationcraft.bot.utils import safe_send

    message = MagicMock()
    calls = []

    async def _answer(text, reply_markup=None, parse_mode=None, **kwargs):
        calls.append({"text": text, "parse_mode": parse_mode})
        if parse_mode == "Markdown" and "_" in text:
            raise TelegramBadRequest(
                method=MagicMock(),
                message="Bad Request: can't parse entities"
            )
        return MagicMock()

    message.answer = _answer

    asyncio.run(safe_send(message, "Hello _world_ parse_mode=Markdown"))
    assert len(calls) == 2, f"expected 2 calls (Markdown + plain), got {len(calls)}"
    assert calls[0]["parse_mode"] == "Markdown"
    assert calls[1]["parse_mode"] is None  # fallback to plain text


# ---------------------------------------------------------------------
# Bug 28: Global error handler catches TelegramNetworkError
# ---------------------------------------------------------------------

def test_bot_has_global_error_handler():
    """The bot dispatcher should have a global error handler that
    catches TelegramNetworkError (WinError 64) and logs it concisely
    without crashing the polling loop.
    """
    import inspect
    from nationcraft.bot.app import build_dispatcher
    source = inspect.getsource(build_dispatcher)
    assert "@dp.error()" in source or "dp.error" in source, (
        "dispatcher should have a global error handler registered via @dp.error()"
    )
    assert "TelegramNetworkError" in source, (
        "error handler should catch TelegramNetworkError (WinError 64)"
    )


# ---------------------------------------------------------------------
# Bug 30: /status uses api_client.health() (in-process fast path)
# ---------------------------------------------------------------------

def test_status_uses_api_client_health():
    """/status should call ``api_client.health()`` instead of creating
    a new ``httpx.AsyncClient`` per call.

    Reasons:
    - The old ``httpx.AsyncClient(timeout=10.0)`` leaked a connection
      pool per /status invocation.
    - On ``--local`` mode (bot + API share one event loop), the HTTP
      roundtrip to localhost can deadlock if the event loop is busy
      with a slow Telegram send. The new ``api_client.health()``
      short-circuits this by checking the in-process uvicorn server
      state directly.
    - The 10s timeout was also too long: if the API was genuinely
      unreachable, the user waited 10s for /status to respond. The
      new helper has a 5s internal timeout.
    """
    from pathlib import Path
    commands_path = Path(__file__).parent.parent / "src" / "nationcraft" / "bot" / "handlers" / "commands.py"
    source = commands_path.read_text()
    # Should call api_client.health()
    assert "await api_client.health()" in source, (
        "/status should use api_client.health() for the API check"
    )
    # Should NOT create a fresh httpx.AsyncClient(timeout=10.0) just
    # for /health (it leaks connections and can't use the in-process
    # fast path).
    assert "timeout=10.0" not in source, (
        "/status should not use httpx.AsyncClient(timeout=10.0) — "
        "use api_client.health() instead (in-process fast path)"
    )
