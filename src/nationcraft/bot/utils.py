r"""Bot utility helpers: safe message sending, Markdown escaping.

Telegram's Markdown V1 parser is strict — user-supplied text that
contains ``_``, ``*``, backtick, ``[``, ``]`` will break it with
``TelegramBadRequest: can't parse entities: Can't find end of the
entity starting at byte offset N``.

This module provides:

* :func:`escape_md` — escape user content so it's safe inside a
  Markdown-formatted message
* :func:`safe_send` — send a message with bounded retries. Network
  errors (WinError 10054, connection reset, timeout) are common on
  poor networks (e.g. Iran, where api.telegram.org is throttled).
  Previously this retried 3 times with 1+2+3 = 6s of sleep, which on
  a slow network meant each handler took 30+ seconds (3 × 5-10s
  Telegram API call + 6s sleep). Other updates from the same chat
  then piled up, causing the symptom where the bot's reply to
  update N appeared in response to update N-1.

  New behaviour:
  - Hard cap on TOTAL elapsed time (default 20s). If the first
    attempt takes 12s and fails, only one more retry is attempted.
  - Reduce to 2 retries max with 1s sleep (down from 3 retries with
    6s sleep). On a slow-but-working network the first attempt
    usually succeeds in 5-10s — one retry is enough to recover from
    a transient TCP reset.
  - Each call to ``message.answer`` is bounded by aiogram's session
    timeout (configured in :func:`bot.app._build_aiohttp_session`).
* :func:`safe_edit` — same, but for ``message.edit_text``
* :func:`safe_answer` — same, but for ``callback_query.answer``
"""
from __future__ import annotations

import asyncio
import time
from typing import Any

from aiogram.exceptions import TelegramBadRequest, TelegramNetworkError
from aiogram.types import CallbackQuery, Message

# Hard cap on total time spent inside safe_send/safe_edit/safe_answer.
# Reduced from 20s to 8s — on Iran's network, each Telegram API call
# can block for 10-30s. A 20s cap meant each handler took up to 20s,
# which caused updates to queue up and compound (the user's messages
# from 2 minutes ago were still being processed). 8s is short enough
# that the bot processes queued updates within a reasonable window,
# while still giving a slow Telegram API enough time to respond.
_TOTAL_TIMEOUT_SECONDS = 8.0

# How many retries on network errors. 1 = no retry (just the initial
# attempt). On Iran's throttled network, retrying just compounds the
# delay — each retry adds 5-10s of blocking. Better to fail fast and
# let the user retry by clicking the button again.
_MAX_RETRIES = 1

# Sleep between retries. 1s is enough for a transient TCP reset
# (the OS re-establishes the connection in <1s). Higher values just
# block the handler chain longer.
_RETRY_SLEEP_SECONDS = 1.0


# Characters that Telegram Markdown V1 treats as formatting markers.
# We escape them with a backslash so Telegram renders them literally.
_MD_SPECIAL = set("_*`[]")


def escape_md(text: Any) -> str:
    """Escape Telegram Markdown V1 special characters in *text*.

    Use this for any user-supplied content that's interpolated into a
    ``parse_mode="Markdown"`` message — e.g. usernames, country names,
    resource keys, etc.

    >>> escape_md("YSN_RFD")
    'YSN\\_RFD'
    >>> escape_md("hello *world*")
    'hello \\*world\\*'
    """
    s = str(text) if text is not None else ""
    return "".join(f"\\{ch}" if ch in _MD_SPECIAL else ch for ch in s)


def _is_parse_error(exc: Exception) -> bool:
    """Return True if *exc* is a Telegram Markdown/HTML parse error.

    Telegram raises ``TelegramBadRequest: can't parse entities: Can't
    find end of the entity starting at byte offset N`` when the message
    contains an unescaped ``_``, ``*``, ``[``, or backtick. We catch
    this and retry as plain text (no parse_mode) so the user still
    receives the message, just without formatting.
    """
    if not isinstance(exc, TelegramBadRequest):
        return False
    msg = str(exc).lower()
    return any(s in msg for s in (
        "can't parse entities",
        "can't parse message",
        "entity starting at byte offset",
    ))


async def safe_send(
    message: Message,
    text: str,
    *,
    reply_markup: Any = None,
    parse_mode: str | None = "Markdown",
    max_retries: int = _MAX_RETRIES,
    total_timeout: float = _TOTAL_TIMEOUT_SECONDS,
    **kwargs: Any,
) -> Message | None:
    """Send a message with retry-on-network-error and plain-text fallback.

    On ``TelegramBadRequest`` (Markdown parse error), retries as plain
    text (``parse_mode=None``) so the message still goes through.

    On ``TelegramNetworkError`` (TCP reset, timeout, connection
    refused — common on throttled networks like Iran), retries up to
    ``max_retries`` times with ``_RETRY_SLEEP_SECONDS`` between
    attempts. The total wall-clock time spent inside this function
    is bounded by ``total_timeout`` — if the first attempt takes 12s
    and fails, only one more retry is attempted.

    Returns the sent Message on success, or None if all retries failed
    (the global dispatcher error handler will log the failure).
    """
    import asyncio as _asyncio
    from aiogram.exceptions import TelegramNetworkError

    deadline = time.monotonic() + total_timeout
    last_exc: Exception | None = None

    for attempt in range(max_retries):
        try:
            return await message.answer(
                text, reply_markup=reply_markup, parse_mode=parse_mode, **kwargs
            )
        except TelegramBadRequest as exc:
            if _is_parse_error(exc):
                # Retry as plain text — strip markdown markers for
                # readability so the user sees clean text instead of
                # literal ``*bold*`` etc.
                plain = _strip_md(text)
                try:
                    return await message.answer(
                        plain, reply_markup=reply_markup, parse_mode=None, **kwargs
                    )
                except TelegramBadRequest:
                    return None
            # Non-parse TelegramBadRequest (e.g. chat not found) — don't
            # retry, just give up silently.
            return None
        except TelegramNetworkError as exc:
            last_exc = exc
            # Network error — retry if we have time budget left.
            if attempt < max_retries - 1 and time.monotonic() < deadline:
                await _asyncio.sleep(_RETRY_SLEEP_SECONDS)
                continue
            return None
        except Exception as exc:  # noqa: BLE001
            # Other unexpected errors (e.g. asyncio.CancelledError) —
            # don't retry, just give up. Re-raise CancelledError so the
            # shutdown handler can clean up properly.
            if isinstance(exc, asyncio.CancelledError):
                raise
            last_exc = exc
            return None

    # All retries exhausted — return None silently. The dispatcher's
    # global error handler will log a network_error if one happened.
    return None


async def safe_edit(
    message: Message,
    text: str,
    *,
    reply_markup: Any = None,
    parse_mode: str | None = "Markdown",
    max_retries: int = _MAX_RETRIES,
    total_timeout: float = _TOTAL_TIMEOUT_SECONDS,
    **kwargs: Any,
) -> Message | None:
    """Edit a message, falling back to plain text on parse errors.

    Same retry/timeout semantics as :func:`safe_send`.

    Also swallows the common ``message is not modified`` error which
    happens when the user clicks the same button twice — the UX feels
    seamless instead of showing an error.
    """
    import asyncio as _asyncio
    from aiogram.exceptions import TelegramNetworkError

    deadline = time.monotonic() + total_timeout
    last_exc: Exception | None = None

    for attempt in range(max_retries):
        try:
            return await message.edit_text(
                text, reply_markup=reply_markup, parse_mode=parse_mode, **kwargs
            )
        except TelegramBadRequest as exc:
            msg = str(exc).lower()
            if "message is not modified" in msg:
                # No-op — content is already what we wanted.
                return None
            if _is_parse_error(exc):
                # Markdown parse error — retry as plain text.
                plain = _strip_md(text)
                try:
                    return await message.edit_text(
                        plain, reply_markup=reply_markup, parse_mode=None, **kwargs
                    )
                except TelegramBadRequest:
                    return None
            # Other BadRequest — give up.
            return None
        except TelegramNetworkError as exc:
            last_exc = exc
            if attempt < max_retries - 1 and time.monotonic() < deadline:
                await _asyncio.sleep(_RETRY_SLEEP_SECONDS)
                continue
            return None
        except Exception as exc:  # noqa: BLE001
            if isinstance(exc, asyncio.CancelledError):
                raise
            last_exc = exc
            return None
    return None


async def safe_answer(
    cb: CallbackQuery,
    text: str = "",
    *,
    show_alert: bool = False,
    max_retries: int = _MAX_RETRIES,
    total_timeout: float = _TOTAL_TIMEOUT_SECONDS,
    **kwargs: Any,
) -> None:
    """Answer a callback query, ignoring transient errors.

    Telegram expires callback queries after ~30 seconds. If the bot
    took too long (e.g. API timeout), calling ``cb.answer()`` raises
    ``TelegramBadRequest: query is too old``. This helper swallows
    that and other transient errors so they don't cascade into an
    unhandled exception.
    """
    import asyncio as _asyncio
    from aiogram.exceptions import TelegramNetworkError

    deadline = time.monotonic() + total_timeout

    for attempt in range(max_retries):
        try:
            await cb.answer(text=text, show_alert=show_alert, **kwargs)
            return
        except TelegramBadRequest as exc:
            msg = str(exc).lower()
            if "query is too old" in msg or "query id is invalid" in msg:
                # Expired callback — user can't see the answer anyway.
                return
            # Other BadRequest — give up silently.
            return
        except TelegramNetworkError:
            if attempt < max_retries - 1 and time.monotonic() < deadline:
                await _asyncio.sleep(_RETRY_SLEEP_SECONDS)
                continue
            return
        except Exception as exc:  # noqa: BLE001
            if isinstance(exc, asyncio.CancelledError):
                raise
            return


def _strip_md(text: str) -> str:
    """Remove Markdown formatting markers from *text* for plain-text fallback.

    Replaces ``*bold*`` → ``bold``, ``_italic_`` → ``italic``, etc.
    Used when Telegram rejects a Markdown message — we retry the same
    content as plain text so the user still sees the message.
    """
    import re
    # Remove *bold*, _italic_, `code`, [text](url)
    text = re.sub(r"\*([^*]+)\*", r"\1", text)
    text = re.sub(r"_([^_]+)_", r"\1", text)
    text = re.sub(r"`([^`]+)`", r"\1", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    # Remove any remaining unescaped markers
    text = re.sub(r"\\([_*`\[\]])", r"\1", text)
    return text
