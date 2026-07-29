#!/usr/bin/env python3
"""Mock Telegram Bot API server for testing the NationCraft bot end-to-end.

This is a **real** FastAPI server that implements the subset of the Telegram
Bot API that aiogram 3.x uses during polling. It lets us test the bot's
actual HTTP interaction with Telegram without needing network access to
api.telegram.org (which is blocked in some regions, e.g. Iran).

Implemented endpoints (matching the real Telegram Bot API):
  POST /bot{token}/getMe
  POST /bot{token}/getUpdates          (long-poll with timeout)
  POST /bot{token}/sendMessage
  POST /bot{token}/editMessageText
  POST /bot{token}/answerCallbackQuery
  POST /bot{token}/deleteWebhook
  POST /bot{token}/setWebhook
  GET  /bot{token}/getWebhookInfo
  POST /bot{token}/setMyCommands       (no-op, returns ok)

Test-helper endpoints (NOT part of the real Telegram API — used by the
test harness to push updates and inspect what the bot sent):
  POST /test/push_message              → enqueue a Message update
  POST /test/push_callback             → enqueue a CallbackQuery update
  POST /test/push_command              → enqueue a Message update with /command
  GET  /test/sent_messages             → list of all sendMessage calls
  GET  /test/sent_messages/{chat_id}   → messages sent to a specific chat
  POST /test/reset                     → clear all state
  GET  /test/stats                     → counters for each method

Usage:
  python scripts/mock_telegram_server.py --port 8081 --token 12345:fake

The bot then connects by setting:
  TELEGRAM_API_BASE=http://localhost:8081
  TELEGRAM_BOT_TOKEN=12345:fake
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import time
import uuid
from typing import Any

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

log = logging.getLogger("mock_telegram")

# ---------------------------------------------------------------------------
# In-memory state — a fresh instance is created per test run via /test/reset.
# ---------------------------------------------------------------------------

class MockState:
    """All mutable state for the mock Telegram server."""

    def __init__(self) -> None:
        self.lock = asyncio.Lock()
        # The next update_id to assign. Telegram update_ids start at 1
        # and must be strictly increasing so the bot can ack them.
        self._next_update_id: int = 1
        # Pending updates waiting for getUpdates to pick up.
        self.updates_queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        # All messages the bot has sent (sendMessage calls), in order.
        self.sent_messages: list[dict[str, Any]] = []
        # All callback queries the bot has answered.
        self.answered_callbacks: list[dict[str, Any]] = []
        # All edited messages.
        self.edited_messages: list[dict[str, Any]] = []
        # Per-chat message_id counter (so editMessageText can find them).
        self.next_message_id: int = 1
        # Stats counters per Telegram method.
        self.stats: dict[str, int] = {}
        # Bot identity (returned by getMe).
        self.bot_info: dict[str, Any] = {
            "id": 8937387510,
            "is_bot": True,
            "first_name": "game bot",
            "username": "gameruletbot",
            "can_join_groups": True,
            "can_read_all_group_messages": False,
            "supports_inline_queries": False,
        }
        # Webhook info (always empty — we're in polling mode).
        self.webhook_info: dict[str, Any] = {
            "url": "",
            "has_custom_certificate": False,
            "pending_update_count": 0,
        }

    def reset(self) -> None:
        """Clear sent-messages state. Safe to call between tests.

        NOTE: We do NOT replace the ``updates_queue`` — the bot's
        getUpdates long-poll is awaiting on the current queue object.
        Replacing it would orphan the bot's wait. Instead we drain
        it in-place.

        We also do NOT reset ``_next_update_id`` or ``next_message_id``
        because the bot tracks the last update_id it acked (via the
        offset parameter in getUpdates). If we reset update_ids back
        to 1, the bot would drop all new updates with id <= its last
        acked offset.
        """
        # Drain the queue in-place (don't replace it — the bot is
        # awaiting on this specific queue object via getUpdates).
        while not self.updates_queue.empty():
            try:
                self.updates_queue.get_nowait()
            except asyncio.QueueEmpty:
                break
        self.sent_messages.clear()
        self.answered_callbacks.clear()
        self.edited_messages.clear()
        self.stats.clear()
        # Don't reset bot_info, _next_update_id, or next_message_id —
        # see the note above.

    def bump_stat(self, method: str) -> None:
        self.stats[method] = self.stats.get(method, 0) + 1

    def next_update_id(self) -> int:
        uid = self._next_update_id
        self._next_update_id += 1
        return uid


state = MockState()


# ---------------------------------------------------------------------------
# Helpers to build Telegram-style response envelopes.
# ---------------------------------------------------------------------------

def _ok(result: Any) -> dict[str, Any]:
    """Telegram always wraps successful responses in {"ok": true, "result": ...}."""
    return {"ok": True, "result": result}


def _error(description: str, error_code: int = 400) -> dict[str, Any]:
    return {"ok": False, "error_code": error_code, "description": description}


def _make_user(user_id: int, first_name: str = "Tester", username: str = "tester", language_code: str = "en") -> dict[str, Any]:
    return {
        "id": user_id,
        "is_bot": False,
        "first_name": first_name,
        "username": username,
        "language_code": language_code,
    }


def _make_chat(chat_id: int, type_: str = "private", title: str | None = None) -> dict[str, Any]:
    chat: dict[str, Any] = {"id": chat_id, "type": type_}
    if title:
        chat["title"] = title
    return chat


def _make_message(
    *,
    message_id: int,
    chat_id: int,
    text: str,
    from_user: dict[str, Any],
    date: int | None = None,
    reply_markup: dict[str, Any] | None = None,
) -> dict[str, Any]:
    msg: dict[str, Any] = {
        "message_id": message_id,
        "date": date or int(time.time()),
        "chat": _make_chat(chat_id),
        "from": from_user,
        "text": text,
    }
    if reply_markup:
        msg["reply_markup"] = reply_markup
    return msg


# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------

app = FastAPI(title="Mock Telegram Bot API")


def _token_from_path(path: str) -> str | None:
    """Extract the bot token from a path like /bot{token}/getMe."""
    if not path.startswith("/bot"):
        return None
    rest = path[len("/bot"):]
    slash = rest.find("/")
    if slash == -1:
        return None
    return rest[:slash]


# ----- Telegram Bot API endpoints -----
#
# NOTE: aiogram URL-encodes the colon in the bot token (e.g. /bot123%3Aabc/getMe),
# so we can't use FastAPI's {token} path parameter directly (it would match
# only the literal colon). Instead, we use a regex path that captures the
# token and method separately.

import re

_TOKEN_METHOD_REGEX = r"^/bot[^/]+/(getMe|deleteWebhook|setWebhook|getWebhookInfo|setMyCommands|getMyCommands|getUpdates|sendMessage|editMessageText|answerCallbackQuery|editMessageReplyMarkup|deleteMessage|sendChatAction|getChat|getChatMember|answerInlineQuery|kickChatMember|leaveChat|pinChatMessage|unpinChatMessage)$"


@app.api_route("/bot{rest:path}", methods=["GET", "POST"])
async def telegram_api_dispatcher(rest: str, request: Request) -> dict[str, Any]:
    """Dispatch ANY /bot{token}/{method} request to the right handler.

    This catch-all is necessary because aiogram URL-encodes the colon in
    the bot token (e.g. ``/bot123%3Aabc/getMe``), and FastAPI's ``{token}``
    path parameter doesn't match the URL-encoded form reliably.

    We extract the method from the path (the segment after the last ``/``)
    and dispatch accordingly. The token itself is ignored — the mock
    accepts any token.
    """
    path = request.url.path
    # Decode %3A back to : for readability in logs.
    import urllib.parse
    decoded_path = urllib.parse.unquote(path)

    # Extract the method (last path segment).
    m = re.match(_TOKEN_METHOD_REGEX, decoded_path)
    if not m:
        return _error(f"method not found: {decoded_path}", 404)
    method = m.group(1)
    state.bump_stat(method)

    # Read the body once. aiogram sends requests as multipart/form-data
    # for methods with file uploads, and application/x-www-form-urlencoded
    # for everything else. FastAPI's `await request.form()` handles both.
    form = await request.form()

    if method == "getMe":
        return _ok(state.bot_info)

    if method == "deleteWebhook":
        state.webhook_info["url"] = ""
        return _ok(True)

    if method == "setWebhook":
        url = form.get("url", "")
        state.webhook_info["url"] = url
        return _ok(True)

    if method == "getWebhookInfo":
        return _ok(state.webhook_info)

    if method == "setMyCommands":
        return _ok(True)

    if method == "getMyCommands":
        return _ok([])

    if method == "getUpdates":
        timeout = float(form.get("timeout", 30))
        offset = form.get("offset")
        if offset is not None:
            offset_val = int(offset)
            while not state.updates_queue.empty():
                try:
                    peeked = state.updates_queue.get_nowait()
                    if peeked["update_id"] <= offset_val:
                        continue
                    await state.updates_queue.put(peeked)
                    break
                except asyncio.QueueEmpty:
                    break
        try:
            first = await asyncio.wait_for(
                state.updates_queue.get(),
                timeout=timeout if timeout > 0 else 1.0,
            )
            updates = [first]
            while not state.updates_queue.empty():
                try:
                    updates.append(state.updates_queue.get_nowait())
                except asyncio.QueueEmpty:
                    break
            return _ok(updates)
        except asyncio.TimeoutError:
            return _ok([])

    if method == "sendMessage":
        chat_id = int(form.get("chat_id", 0))
        text = form.get("text", "")
        parse_mode = form.get("parse_mode")
        import json
        reply_markup_str = form.get("reply_markup")
        reply_markup = json.loads(reply_markup_str) if reply_markup_str else None
        message_id = state.next_message_id
        state.next_message_id += 1
        msg = _make_message(
            message_id=message_id,
            chat_id=chat_id,
            text=text,
            from_user=state.bot_info,
            reply_markup=reply_markup,
        )
        stored = dict(msg)
        stored["parse_mode"] = parse_mode
        state.sent_messages.append(stored)
        return _ok(msg)

    if method == "editMessageText":
        message_id = form.get("message_id")
        chat_id = form.get("chat_id")
        text = form.get("text", "")
        import json
        reply_markup_str = form.get("reply_markup")
        reply_markup = json.loads(reply_markup_str) if reply_markup_str else None
        edited = {
            "message_id": int(message_id) if message_id else 0,
            "chat_id": int(chat_id) if chat_id else 0,
            "text": text,
            "reply_markup": reply_markup,
            "edited_at": time.time(),
        }
        state.edited_messages.append(edited)
        msg = _make_message(
            message_id=edited["message_id"],
            chat_id=edited["chat_id"],
            text=text,
            from_user=state.bot_info,
            reply_markup=reply_markup,
        )
        return _ok(msg)

    if method == "answerCallbackQuery":
        callback_query_id = form.get("callback_query_id", "")
        text = form.get("text", "")
        show_alert = form.get("show_alert", "false") == "true"
        state.answered_callbacks.append({
            "callback_query_id": callback_query_id,
            "text": text,
            "show_alert": show_alert,
        })
        return _ok(True)

    if method == "deleteMessage":
        return _ok(True)

    if method == "sendChatAction":
        return _ok(True)

    if method == "editMessageReplyMarkup":
        return _ok(True)

    # Default: return ok=True for any unhandled method so the bot doesn't crash.
    return _ok(True)


# ----- Test-helper endpoints (NOT part of the real Telegram API) -----

@app.post("/test/push_message")
async def test_push_message(request: Request) -> dict[str, Any]:
    """Enqueue a private message update for the bot to receive via getUpdates.

    Body:
        {
          "chat_id": 123,
          "user_id": 456,
          "text": "hello",
          "username": "tester",
          "first_name": "Tester",
          "language_code": "en"
        }
    """
    body = await request.json()
    chat_id = body["chat_id"]
    user_id = body["user_id"]
    text = body.get("text", "")
    username = body.get("username", "tester")
    first_name = body.get("first_name", "Tester")
    language_code = body.get("language_code", "en")

    user = _make_user(user_id, first_name=first_name, username=username, language_code=language_code)
    # Use a separate message_id for user-sent messages (offset by 10000 to
    # avoid collision with bot-sent ones).
    msg = _make_message(
        message_id=state.next_message_id + 10000,
        chat_id=chat_id,
        text=text,
        from_user=user,
    )
    state.next_message_id += 1

    update = {
        "update_id": state.next_update_id(),
        "message": msg,
    }
    await state.updates_queue.put(update)
    return {"ok": True, "update_id": update["update_id"]}


@app.post("/test/push_command")
async def test_push_command(request: Request) -> dict[str, Any]:
    """Enqueue a command (e.g. /start) as a message update.

    Body:
        {
          "chat_id": 123,
          "user_id": 456,
          "command": "start",
          "args": "",
          "username": "tester"
        }
    """
    body = await request.json()
    command = body["command"].lstrip("/")
    args = body.get("args", "")
    text = f"/{command}"
    if args:
        text += " " + args

    # Telegram includes entities to mark the command. aiogram's Command
    # filter looks for entities of type bot_command.
    user = _make_user(
        body["user_id"],
        first_name=body.get("first_name", "Tester"),
        username=body.get("username", "tester"),
        language_code=body.get("language_code", "en"),
    )
    msg = _make_message(
        message_id=state.next_message_id + 10000,
        chat_id=body["chat_id"],
        text=text,
        from_user=user,
    )
    msg["entities"] = [
        {"type": "bot_command", "offset": 0, "length": len(command) + 1}
    ]
    state.next_message_id += 1

    update = {
        "update_id": state.next_update_id(),
        "message": msg,
    }
    await state.updates_queue.put(update)
    return {"ok": True, "update_id": update["update_id"]}


@app.post("/test/push_callback")
async def test_push_callback(request: Request) -> dict[str, Any]:
    """Enqueue a callback_query update (button click).

    Body:
        {
          "chat_id": 123,
          "user_id": 456,
          "message_id": 789,   # the bot's message that had the button
          "data": "menu:home",
          "username": "tester"
        }
    """
    body = await request.json()
    user = _make_user(
        body["user_id"],
        first_name=body.get("first_name", "Tester"),
        username=body.get("username", "tester"),
        language_code=body.get("language_code", "en"),
    )
    callback_id = str(uuid.uuid4())
    # The message the button is attached to. Telegram includes the FULL
    # message object (including its reply_markup) in callback_query.message.
    bot_msg = _make_message(
        message_id=body.get("message_id", 1),
        chat_id=body["chat_id"],
        text="(button message)",
        from_user=state.bot_info,
    )
    update = {
        "update_id": state.next_update_id(),
        "callback_query": {
            "id": callback_id,
            "from": user,
            "message": bot_msg,
            "chat_instance": str(uuid.uuid4())[:8],
            "data": body["data"],
        },
    }
    await state.updates_queue.put(update)
    return {"ok": True, "update_id": update["update_id"], "callback_query_id": callback_id}


@app.get("/test/sent_messages")
async def test_get_sent_messages() -> dict[str, Any]:
    """Return all messages the bot has sent via sendMessage."""
    return {"messages": state.sent_messages, "count": len(state.sent_messages)}


@app.get("/test/sent_messages/{chat_id}")
async def test_get_sent_messages_for_chat(chat_id: int) -> dict[str, Any]:
    """Return messages the bot sent to a specific chat."""
    msgs = [m for m in state.sent_messages if m["chat"]["id"] == chat_id]
    return {"messages": msgs, "count": len(msgs)}


@app.get("/test/edited_messages")
async def test_get_edited_messages() -> dict[str, Any]:
    return {"messages": state.edited_messages, "count": len(state.edited_messages)}


@app.get("/test/answered_callbacks")
async def test_get_answered_callbacks() -> dict[str, Any]:
    return {"callbacks": state.answered_callbacks, "count": len(state.answered_callbacks)}


@app.get("/test/stats")
async def test_get_stats() -> dict[str, Any]:
    return {"stats": state.stats}


@app.get("/test/queue_size")
async def test_get_queue_size() -> dict[str, Any]:
    return {"queue_size": state.updates_queue.qsize()}


@app.post("/test/reset")
async def test_reset() -> dict[str, Any]:
    state.reset()
    return {"ok": True}


@app.get("/test/health")
async def test_health() -> dict[str, Any]:
    return {"ok": True, "service": "mock-telegram-bot-api"}


# ---------------------------------------------------------------------------
# Main entrypoint
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Mock Telegram Bot API server")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8081)
    parser.add_argument("--token", default="123456:fake-token-for-testing",
                        help="The bot token this server expects (any token is accepted).")
    parser.add_argument("--log-level", default="warning")
    args = parser.parse_args()

    # Quiet uvicorn's access log so the test output is readable.
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)

    uvicorn.run(
        app,
        host=args.host,
        port=args.port,
        log_level=args.log_level,
        access_log=False,
    )


if __name__ == "__main__":
    main()
