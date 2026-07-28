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
# Bug 24: Pre-flight API check raced with API startup
# ---------------------------------------------------------------------

def test_bot_pre_flight_check_retries():
    """The pre-flight API check should retry for up to 30 seconds,
    not fail immediately. We verify by reading the source code that
    the retry loop exists.
    """
    import inspect
    from nationcraft.bot.app import run_bot
    source = inspect.getsource(run_bot)
    # The retry loop should be present.
    assert "for attempt in range" in source, (
        "run_bot should have a retry loop for the pre-flight API check"
    )
    # Should retry at least 10 times (15 * 2s = 30s).
    assert "range(15)" in source or "range(10)" in source or "range(20)" in source, (
        "pre-flight check should retry at least 10 times"
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

def test_api_client_timeout_is_15s():
    """The API client read timeout should be 15s (was 5s).
    Argon2 hashing takes ~500ms on Windows/Python 3.11; combined with
    DB I/O the total can exceed 5s, causing httpx.ReadTimeout.
    """
    from nationcraft.bot.api_client import _DEFAULT_TIMEOUT
    assert _DEFAULT_TIMEOUT.read == pytest.approx(15.0), (
        f"expected read timeout=15.0s, got {_DEFAULT_TIMEOUT.read}s"
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
