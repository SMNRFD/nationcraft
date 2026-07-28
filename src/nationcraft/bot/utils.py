r"""Bot utility helpers: safe message sending, Markdown escaping.

Telegram's Markdown V1 parser is strict — any user-supplied text that
contains ``_``, ``*``, backtick, ``[``, ``]`` will break it with
``TelegramBadRequest: can't parse entities: Can't find end of the
entity starting at byte offset N``.

This module provides:

* :func:`escape_md` — escape user content so it's safe inside a
  Markdown-formatted message.
* :func:`safe_send` — send a message; if Telegram rejects it due to a
  parse error, automatically retry as plain text (no parse_mode).
* :func:`safe_edit` — same, but for ``message.edit_text``.
* :func:`safe_answer` — same, but for ``callback_query.answer``.
"""
from __future__ import annotations

from typing import Any

from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder


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
    """Return True if *exc* is a Telegram Markdown/HTML parse error."""
    if not isinstance(exc, TelegramBadRequest):
        return False
    msg = str(exc).lower()
    return any(kw in msg for kw in (
        "can't parse entities",
        "can't parse entities:",
        "bad request: can't parse",
        "entity",
    ))


async def safe_send(
    message: Message,
    text: str,
    *,
    reply_markup: Any = None,
    parse_mode: str | None = "Markdown",
    max_retries: int = 3,
    **kwargs: Any,
) -> Message | None:
    """Send a message with retry, fallback to plain text on parse errors.

    Retries up to ``max_retries`` times on network errors (WinError 10054,
    connection reset, timeout) — common on poor networks. If Telegram
    rejects the message due to a Markdown parse error, retries as plain
    text (``parse_mode=None``).
    """
    import asyncio as _asyncio
    from aiogram.exceptions import TelegramNetworkError

    last_exc = None
    for attempt in range(max_retries):
        try:
            return await message.answer(
                text, reply_markup=reply_markup, parse_mode=parse_mode, **kwargs
            )
        except TelegramBadRequest as exc:
            if _is_parse_error(exc):
                # Retry as plain text (strip markdown markers for readability).
                plain = _strip_md(text)
                try:
                    return await message.answer(
                        plain, reply_markup=reply_markup, parse_mode=None, **kwargs
                    )
                except TelegramBadRequest:
                    return None
            # Non-parse TelegramBadRequest — re-raise.
            raise
        except TelegramNetworkError as exc:
            last_exc = exc
            # Network error (WinError 10054, timeout, connection reset).
            # Wait briefly and retry — the connection will be re-established
            # by aiohttp automatically.
            if attempt < max_retries - 1:
                await _asyncio.sleep(1.0 * (attempt + 1))  # 1s, 2s, 3s
            continue
        except Exception as exc:
            # Other unexpected errors — log and give up.
            last_exc = exc
            break
    # All retries failed — return None silently (the global error handler
    # will log the network error).
    return None


async def safe_edit(
    message: Message,
    text: str,
    *,
    reply_markup: Any = None,
    parse_mode: str | None = "Markdown",
    **kwargs: Any,
) -> Message | None:
    """Edit a message, falling back to plain text on parse errors.

    Also ignores the common "message is not modified" error (which
    happens when the user clicks the same button twice).
    """
    try:
        return await message.edit_text(
            text, reply_markup=reply_markup, parse_mode=parse_mode, **kwargs
        )
    except TelegramBadRequest as exc:
        if _is_parse_error(exc):
            plain = _strip_md(text)
            try:
                return await message.edit_text(
                    plain, reply_markup=reply_markup, parse_mode=None, **kwargs
                )
            except TelegramBadRequest:
                return None
        if "message is not modified" in str(exc).lower():
            return None
        raise


async def safe_answer(
    cb: CallbackQuery,
    text: str = "",
    *,
    show_alert: bool = False,
    **kwargs: Any,
) -> None:
    """Answer a callback query, ignoring 'query is too old' errors."""
    try:
        await cb.answer(text=text, show_alert=show_alert, **kwargs)
    except TelegramBadRequest as exc:
        msg = str(exc).lower()
        if "query is too old" in msg or "query id is invalid" in msg:
            pass
        else:
            raise


def _strip_md(text: str) -> str:
    """Remove Markdown formatting markers from *text* for plain-text fallback.

    Replaces ``*bold*`` → ``bold``, ``_italic_`` → ``italic``, etc.
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
