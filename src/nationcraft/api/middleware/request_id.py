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
    """Injects an X-Request-Id into every request and response."""

    async def dispatch(self, request: Request, call_next):  # type: ignore[no-untyped-def]
        rid = request.headers.get("x-request-id") or str(uuid.uuid4())
        request.state.request_id = rid
        start = time.perf_counter()
        response: Response = await call_next(request)
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
