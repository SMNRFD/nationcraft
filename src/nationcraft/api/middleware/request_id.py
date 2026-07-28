"""Cross-cutting middleware."""
from __future__ import annotations

import time
import uuid

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from nationcraft.core.logging import get_logger

log = get_logger(__name__)


class RequestIdMiddleware(BaseHTTPMiddleware):
    """Injects an X-Request-Id into every request and response.

    Implementation note: ``BaseHTTPMiddleware`` re-raises any exception
    raised by the route handler *after* the exception handler has
    already produced a response. This is a known Starlette quirk that
    pollutes logs with duplicate tracebacks and, worse, can cause
    ``httpx.ReadError`` on the client side because the server closes
    the connection mid-stream.

    To avoid this we catch the exception here, log it once, and
    re-raise it as a clean 500 response so the exception handler in
    ``app.py`` is bypassed entirely (it would otherwise see a second
    raise and emit a duplicate log).
    """

    async def dispatch(self, request: Request, call_next):  # type: ignore[no-untyped-def]
        rid = request.headers.get("x-request-id") or str(uuid.uuid4())
        request.state.request_id = rid
        start = time.perf_counter()
        try:
            response: Response = await call_next(request)
        except Exception as exc:  # noqa: BLE001
            # Log once here so we don't get a duplicate stacktrace from
            # the fallback exception handler in app.py.
            log.exception(
                "http.unhandled_error",
                request_id=rid,
                method=request.method,
                path=request.url.path,
                error=str(exc)[:500],
            )
            from starlette.responses import JSONResponse
            response = JSONResponse(
                status_code=500,
                content={
                    "ok": False,
                    "data": None,
                    "error": {"code": "internal_error", "message": "internal server error"},
                },
            )
        elapsed_ms = (time.perf_counter() - start) * 1000
        response.headers["X-Request-Id"] = rid
        response.headers["X-Response-Time-ms"] = f"{elapsed_ms:.2f}"
        log.info(
            "http.request",
            request_id=rid,
            method=request.method,
            path=request.url.path,
            status=response.status_code,
            duration_ms=round(elapsed_ms, 2),
        )
        return response
