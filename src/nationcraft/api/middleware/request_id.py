"""Cross-cutting middleware — pure ASGI implementation.

This middleware replaces the previous ``BaseHTTPMiddleware``-based
version. ``BaseHTTPMiddleware`` has well-known issues when the ASGI
app and an HTTP client share the same event loop (which is exactly
what happens when running ``python main.py --local`` — the bot's
httpx client and the API's uvicorn server share one asyncio loop):

* It wraps each request in a task that communicates via a background
  task + anyio memory object stream. Under concurrent load (the bot
  fires 2-3 requests per update), the stream can deadlock, causing
  uvicorn to return ``502 Bad Gateway`` and the client to see
  ``httpx.ReadError``.

* It re-raises exceptions after the exception handler has already
  produced a response, polluting logs with duplicate tracebacks.

The pure-ASGI implementation below avoids both issues by operating
directly on the ``(scope, receive, send)`` tuple — no background
tasks, no streams, no deadlock.
"""
from __future__ import annotations

import time
import uuid

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from nationcraft.core.logging import get_logger

log = get_logger(__name__)


class RequestIdMiddleware:
    """Injects an X-Request-Id into every request and response.

    Pure ASGI middleware (not ``BaseHTTPMiddleware``). This avoids the
    deadlock/502 issues that ``BaseHTTPMiddleware`` causes when the
    event loop is shared between the API server and an HTTP client
    (e.g. the Telegram bot's api_client calling localhost:8000 from
    the same process).
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        rid = None
        # Extract request ID from headers.
        for name, value in scope.get("headers", []):
            if name == b"x-request-id":
                rid = value.decode("latin-1")
                break
        if not rid:
            rid = str(uuid.uuid4())

        scope.setdefault("state", {})
        scope["state"]["request_id"] = rid

        start = time.perf_counter()
        status_code = 0
        headers_sent = False

        async def send_wrapper(message: Message) -> None:
            nonlocal status_code, headers_sent
            if message["type"] == "http.response.start":
                status_code = message["status"]
                # Inject our headers into the response.
                headers = list(message.get("headers", []))
                headers.append((b"x-request-id", rid.encode("latin-1")))
                elapsed_ms = (time.perf_counter() - start) * 1000
                headers.append(
                    (b"x-response-time-ms", f"{elapsed_ms:.2f}".encode("latin-1"))
                )
                message["headers"] = headers
                headers_sent = True
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        except Exception as exc:  # noqa: BLE001
            # If headers haven't been sent yet, we can still send an
            # error response. If they have, we can only log.
            elapsed_ms = (time.perf_counter() - start) * 1000
            log.exception(
                "http.unhandled_error",
                request_id=rid,
                method=scope.get("method", "?"),
                path=scope.get("path", "?"),
                error=str(exc)[:500],
                duration_ms=round(elapsed_ms, 2),
            )
            if not headers_sent:
                # Send a clean 500 JSON response.
                import json
                body = json.dumps({
                    "ok": False,
                    "data": None,
                    "error": {
                        "code": "internal_error",
                        "message": "internal server error",
                    },
                }).encode("utf-8")
                await send({
                    "type": "http.response.start",
                    "status": 500,
                    "headers": [
                        (b"content-type", b"application/json"),
                        (b"x-request-id", rid.encode("latin-1")),
                    ],
                })
                await send({
                    "type": "http.response.body",
                    "body": body,
                })
            else:
                # Headers already sent — close the connection.
                await send({"type": "http.disconnect"})
            return

        elapsed_ms = (time.perf_counter() - start) * 1000
        log.info(
            "http.request",
            request_id=rid,
            method=scope.get("method", "?"),
            path=scope.get("path", "?"),
            status=status_code,
            duration_ms=round(elapsed_ms, 2),
        )
