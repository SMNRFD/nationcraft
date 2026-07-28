"""Tests for the Markdown parsing and bot resilience fixes.

Covers:
- escape_md escapes Telegram Markdown special characters
- _strip_md removes formatting markers for plain-text fallback
- is_transient_error classifies 502/503/504 as transient
- api_client gives a clear error message for non-JSON 502 responses
"""
from __future__ import annotations

import pytest


# ---------------------------------------------------------------------
# escape_md
# ---------------------------------------------------------------------

def test_escape_md_escapes_underscore():
    """Underscores in usernames break Telegram Markdown — they must be escaped."""
    from nationcraft.bot.utils import escape_md
    assert escape_md("YSN_RFD") == r"YSN\_RFD"
    assert escape_md("hello_world") == r"hello\_world"


def test_escape_md_escapes_asterisk():
    from nationcraft.bot.utils import escape_md
    assert escape_md("hello *world*") == r"hello \*world\*"


def test_escape_md_escapes_backtick_and_brackets():
    from nationcraft.bot.utils import escape_md
    assert escape_md("code `here`") == r"code \`here\`"
    assert escape_md("[link]") == r"\[link\]"


def test_escape_md_passes_through_plain_text():
    from nationcraft.bot.utils import escape_md
    assert escape_md("Hello World") == "Hello World"
    assert escape_md("Japan 🇯🇵") == "Japan 🇯🇵"
    assert escape_md("") == ""
    assert escape_md(None) == ""


def test_escape_md_handles_non_string():
    from nationcraft.bot.utils import escape_md
    assert escape_md(12345) == "12345"
    assert escape_md(3.14) == "3.14"


# ---------------------------------------------------------------------
# _strip_md
# ---------------------------------------------------------------------

def test_strip_md_removes_bold():
    from nationcraft.bot.utils import _strip_md
    assert _strip_md("*bold text*") == "bold text"


def test_strip_md_removes_italic():
    from nationcraft.bot.utils import _strip_md
    assert _strip_md("_italic text_") == "italic text"


def test_strip_md_removes_code():
    from nationcraft.bot.utils import _strip_md
    assert _strip_md("`code`") == "code"


def test_strip_md_removes_links():
    from nationcraft.bot.utils import _strip_md
    assert _strip_md("[click here](http://example.com)") == "click here"


def test_strip_md_preserves_plain_text():
    from nationcraft.bot.utils import _strip_md
    assert _strip_md("Hello World") == "Hello World"


def test_strip_md_handles_mixed():
    from nationcraft.bot.utils import _strip_md
    result = _strip_md("Welcome to *NationCraft*, _user_!")
    assert result == "Welcome to NationCraft, user!"


# ---------------------------------------------------------------------
# is_transient_error
# ---------------------------------------------------------------------

def test_is_transient_error_502():
    """A 502 Bad Gateway is a transient error (user can retry)."""
    from nationcraft.core.exceptions import NationCraftError, is_transient_error
    exc = NationCraftError("server error", code="api_error", status_code=502)
    assert is_transient_error(exc) is True


def test_is_transient_error_503():
    from nationcraft.core.exceptions import NationCraftError, is_transient_error
    exc = NationCraftError("unavailable", code="api_error", status_code=503)
    assert is_transient_error(exc) is True


def test_is_transient_error_504():
    from nationcraft.core.exceptions import NationCraftError, is_transient_error
    exc = NationCraftError("timeout", code="api_error", status_code=504)
    assert is_transient_error(exc) is True


def test_is_transient_error_api_unreachable_code():
    from nationcraft.core.exceptions import NationCraftError, is_transient_error
    exc = NationCraftError("cannot reach server", code="api_unreachable", status_code=503)
    assert is_transient_error(exc) is True


def test_is_not_transient_error_401():
    """A 401 auth error is NOT transient — the user must re-authenticate."""
    from nationcraft.core.exceptions import NationCraftError, is_transient_error
    exc = NationCraftError("invalid credentials", code="authentication_failed", status_code=401)
    assert is_transient_error(exc) is False


def test_is_not_transient_error_409():
    from nationcraft.core.exceptions import NationCraftError, is_transient_error
    exc = NationCraftError("player exists", code="player_exists", status_code=409)
    assert is_transient_error(exc) is False


def test_is_not_transient_error_400():
    from nationcraft.core.exceptions import NationCraftError, is_transient_error
    exc = NationCraftError("bad request", code="game_rule_violation", status_code=400)
    assert is_transient_error(exc) is False


def test_is_not_transient_error_non_exception():
    from nationcraft.core.exceptions import is_transient_error
    assert is_transient_error("not an exception") is False
    assert is_transient_error(None) is False


# ---------------------------------------------------------------------
# api_client gives clear error for non-JSON 502
# ---------------------------------------------------------------------

@pytest.mark.asyncio
async def test_api_client_502_gives_clear_message():
    """When the API returns 502 with non-JSON body, the error message
    should be user-friendly (not 'invalid response:').
    """
    from unittest.mock import AsyncMock, MagicMock
    from nationcraft.bot.api_client import ApiClient
    from nationcraft.core.exceptions import NationCraftError, is_transient_error

    client = ApiClient(base_url="http://test")

    # Mock httpx to return 502 with empty/non-JSON body.
    mock_resp = MagicMock()
    mock_resp.status_code = 502
    mock_resp.text = ""  # empty body (uvicorn 502 page might be empty)
    mock_resp.json.side_effect = ValueError("not JSON")

    mock_client = AsyncMock()
    mock_client.request = AsyncMock(return_value=mock_resp)
    mock_client.is_closed = False
    client._client = mock_client

    with pytest.raises(NationCraftError) as exc_info:
        await client._request("GET", "/anything", telegram_id=123)

    err = exc_info.value
    # The error message should be user-friendly, not "invalid response:"
    assert "invalid response:" not in str(err), (
        f"error message should not be 'invalid response:', got: {err}"
    )
    assert "unavailable" in str(err).lower() or "try again" in str(err).lower(), (
        f"error should mention unavailability/try-again, got: {err}"
    )
    # Should be classified as transient so the bot lets the user retry.
    assert is_transient_error(err) is True


@pytest.mark.asyncio
async def test_api_client_503_gives_clear_message():
    """Same for 503."""
    from unittest.mock import AsyncMock, MagicMock
    from nationcraft.bot.api_client import ApiClient
    from nationcraft.core.exceptions import NationCraftError, is_transient_error

    client = ApiClient(base_url="http://test")
    mock_resp = MagicMock()
    mock_resp.status_code = 503
    mock_resp.text = "Service Unavailable"
    mock_resp.json.side_effect = ValueError("not JSON")

    mock_client = AsyncMock()
    mock_client.request = AsyncMock(return_value=mock_resp)
    mock_client.is_closed = False
    client._client = mock_client

    with pytest.raises(NationCraftError) as exc_info:
        await client._request("GET", "/anything", telegram_id=456)

    err = exc_info.value
    assert is_transient_error(err) is True
    assert "invalid response:" not in str(err)


# ---------------------------------------------------------------------
# safe_send retries as plain text on Markdown parse error
# ---------------------------------------------------------------------

@pytest.mark.asyncio
async def test_safe_send_falls_back_to_plain_text():
    """If Telegram rejects a Markdown message, safe_send should retry
    as plain text (no parse_mode).
    """
    from unittest.mock import AsyncMock, MagicMock
    from aiogram.exceptions import TelegramBadRequest
    from nationcraft.bot.utils import safe_send

    message = MagicMock()
    message.answer = AsyncMock()

    call_count = {"n": 0}

    async def _answer(text, reply_markup=None, parse_mode=None, **kwargs):
        call_count["n"] += 1
        if parse_mode == "Markdown" and "*" in text:
            raise TelegramBadRequest(
                method=MagicMock(),
                message="Bad Request: can't parse entities: Can't find end of the entity"
            )
        return MagicMock()

    message.answer = _answer

    await safe_send(message, "Hello *broken markdown*", parse_mode="Markdown")
    # Should have been called twice: first with Markdown (failed),
    # then with plain text (succeeded).
    assert call_count["n"] == 2, f"expected 2 calls, got {call_count['n']}"


@pytest.mark.asyncio
async def test_safe_send_succeeds_first_try():
    """If the Markdown is valid, safe_send should NOT retry."""
    from unittest.mock import AsyncMock, MagicMock
    from nationcraft.bot.utils import safe_send

    message = MagicMock()
    call_count = {"n": 0}

    async def _answer(text, reply_markup=None, parse_mode=None, **kwargs):
        call_count["n"] += 1
        return MagicMock()

    message.answer = _answer

    await safe_send(message, "Hello *valid* markdown", parse_mode="Markdown")
    assert call_count["n"] == 1, f"expected 1 call, got {call_count['n']}"


# ---------------------------------------------------------------------
# RequestIdMiddleware is a pure ASGI middleware (no BaseHTTPMiddleware)
# ---------------------------------------------------------------------

def test_request_id_middleware_is_pure_asgi():
    """The middleware should be a pure ASGI callable, NOT based on
    BaseHTTPMiddleware (which causes 502/deadlock issues under load).
    """
    from nationcraft.api.middleware.request_id import RequestIdMiddleware
    from starlette.middleware.base import BaseHTTPMiddleware

    # The middleware class should NOT be a subclass of BaseHTTPMiddleware.
    assert not issubclass(RequestIdMiddleware, BaseHTTPMiddleware), (
        "RequestIdMiddleware must NOT extend BaseHTTPMiddleware — "
        "it causes 502 Bad Gateway under concurrent load when the "
        "event loop is shared (e.g. bot+API in one process)."
    )

    # It should have a plain __call__ method (ASGI interface).
    assert hasattr(RequestIdMiddleware, "__call__"), (
        "RequestIdMiddleware must be an ASGI callable"
    )


@pytest.mark.asyncio
async def test_request_id_middleware_handles_concurrent_requests():
    """The pure-ASGI middleware should handle 10 concurrent requests
    without any returning 502. (BaseHTTPMiddleware would deadlock.)
    """
    import asyncio
    from httpx import ASGITransport, AsyncClient
    from nationcraft.api.app import create_app
    from nationcraft.api.dependencies import get_session
    from nationcraft.infrastructure.db.models import Base
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(bind=engine, expire_on_commit=False, class_=AsyncSession)

    async def override_session():
        async with maker() as s:
            try:
                yield s
                await s.commit()
            except Exception:
                await s.rollback()
                raise

    app = create_app()
    app.dependency_overrides[get_session] = override_session

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # Fire 10 concurrent /health requests.
        tasks = [client.get("/health") for _ in range(10)]
        responses = await asyncio.gather(*tasks)

    await engine.dispose()

    for r in responses:
        assert r.status_code == 200, f"expected 200, got {r.status_code}: {r.text}"
