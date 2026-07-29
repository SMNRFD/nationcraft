"""Bot API client — thin HTTP wrapper around the FastAPI backend.

Key design choices
------------------
* **Per-call timeouts** keyed to the expected latency of the call:
  - Auth + light reads: 8s read (Argon2 takes ~500ms on slow Windows
    machines; with DB I/O and event-bus publish the total can spike
    to 4-5s. 8s gives margin without making the user wait 15s when
    the API is genuinely broken).
  - The default (used when no timeout is passed) is 8s — short
    enough that the bot can recover and process queued updates, long
    enough that legitimate slow Argon2 calls don't time out.

  The previous global 15s timeout was the direct cause of the
  reported 19-38s update durations on slow Iranian networks: a
  single hung API call blocked the bot's per-chat dispatcher for
  15s, then ``safe_send`` added another 5-10s for the Telegram reply,
  then the next queued update repeated the cycle.

* **In-process fast path** when the bot and API share one process
  (``python main.py --local``): a module-level flag lets callers
  short-circuit HTTP for ``/health`` and ``/auth/register`` by
  checking the API server's running state and the DB directly. This
  avoids the localhost HTTP roundtrip that, when the event loop was
  blocked, never completed.

* Stale tokens are evicted on every 401. Previously a single 401 left
  a dead token in ``self._tokens`` forever, so every subsequent call
  failed and the user had to type /login again to recover.

* Automatic refresh-token rotation: when a 401 is received AND we
  have a refresh token stored, the client transparently calls
  ``/auth/refresh``, stores the new pair, and retries the original
  request once. This eliminates the 15-minute cliff caused by
  ``JWT_ACCESS_TTL_SECONDS=900`` with no refresh flow.

* Refresh failures invalidate the local session (both tokens removed).
"""
from __future__ import annotations

import asyncio
from typing import Any

import httpx

from nationcraft.core.config import settings
from nationcraft.core.exceptions import NationCraftError, AuthenticationError, is_transient_error


# Per-call timeouts:
# - 8s read (was 15s — too long, made every hung API call block the
#   bot's per-chat dispatcher for 15s, which queued all subsequent
#   updates and made the user see stale replies)
# - 2s connect (DNS+TCP)
# - 5s write, 2s pool
#
# Argon2 hashing is run in a thread executor (see passwords.py) and
# takes ~500ms on a typical machine. Including DB I/O and event-bus
# publish, the total /auth/register latency rarely exceeds 2-3s. 8s
# gives comfortable margin for slow Windows machines while still
# letting the bot recover quickly when the API is genuinely broken.
_DEFAULT_TIMEOUT = httpx.Timeout(8.0, connect=2.0, write=5.0, pool=2.0)

# A more generous timeout for the register/login endpoints — Argon2
# with the default RFC 9106 parameters (64 MiB memory, 3 iterations,
# 2 parallelism) can take 1-2s on a slow machine under load. We'd
# rather wait than tell the user "timeout" when the operation is
# actually succeeding.
_AUTH_TIMEOUT = httpx.Timeout(12.0, connect=2.0, write=5.0, pool=2.0)

_DEFAULT_LIMITS = httpx.Limits(max_connections=30, max_keepalive_connections=15)


# In-process fast-path: set by main.py when running --local (bot +
# API share one event loop). When True, /health and other hot-path
# calls can short-circuit the HTTP roundtrip. This eliminates the
# failure mode where the bot blocks the very event loop that the API
# needs to answer the bot's HTTP call.
_in_process_api: bool = False

# Optional: a callable that returns True if the API server is
# currently serving. Set by main.run_all via ``set_in_process_api``.
# This decouples the api_client from the uvicorn Server object (which
# lives in main.py at the project root, not inside the nationcraft
# package), avoiding an import cycle.
_is_api_serving: "callable[[], bool] | None" = None


def set_in_process_api(enabled: bool, is_serving: "callable[[], bool] | None" = None) -> None:
    """Mark that the bot and API share one event loop.

    Called by ``main.run_all`` after the API server is up. When True,
    ``ApiClient.health`` and other hot-path calls can check the API
    server's running state directly instead of going through HTTP —
    avoiding the deadlock where the bot's HTTP call waits for a
    response from an event loop that the bot itself is blocking.

    Args:
        enabled: True if the bot and API share one event loop (--local).
        is_serving: Optional callable that returns True if the API
            server is currently serving (e.g.
            ``lambda: _api_server is not None and not _api_server.should_exit``).
            If None, the in-process fast path only checks ``enabled``.
    """
    global _in_process_api, _is_api_serving
    _in_process_api = enabled
    _is_api_serving = is_serving


def is_in_process_api() -> bool:
    """Return True if the bot and API share one event loop (--local)."""
    return _in_process_api


class ApiClient:
    """Wraps REST calls to the backend, with auto token + refresh handling."""

    def __init__(self, base_url: str | None = None) -> None:
        # If base_url is provided, use it. Otherwise, read it dynamically
        # from settings on each request so that --local overrides are
        # picked up even if the singleton was created before the override
        # was applied. This was a real bug: with `.env` setting
        # API_BASE_URL=http://api:8000 (Docker hostname), running
        # `python main.py --local` updated settings.API_BASE_URL but
        # NOT api_client.base_url, so the bot kept trying to reach the
        # Docker hostname and failed.
        self._explicit_base_url = base_url
        # telegram_id -> access_token (short-lived JWT, exp in 15min)
        self._tokens: dict[int, str] = {}
        # telegram_id -> refresh_token (long-lived JWT, exp in 30d)
        self._refresh_tokens: dict[int, str] = {}
        # Per-telegram_id refresh lock — prevents two coroutines from
        # refreshing the same player's token simultaneously.
        self._refresh_locks: dict[int, asyncio.Lock] = {}
        self._client: httpx.AsyncClient | None = None
        self._client_lock = asyncio.Lock()

    @property
    def base_url(self) -> str:
        """Dynamic base URL — always reads from settings unless an
        explicit base_url was passed to __init__.
        """
        if self._explicit_base_url:
            return self._explicit_base_url.rstrip("/")
        return (settings.API_BASE_URL or "http://localhost:8000").rstrip("/")

    async def _get_client(self) -> httpx.AsyncClient:
        """Lazily create a shared httpx client with bounded timeouts.

        Uses a lock to prevent two coroutines from each creating a client
        when ``_client is None`` (which would leak the loser's connection
        pool).
        """
        if self._client is not None and not self._client.is_closed:
            return self._client
        async with self._client_lock:
            if self._client is None or self._client.is_closed:
                self._client = httpx.AsyncClient(
                    timeout=_DEFAULT_TIMEOUT,
                    limits=_DEFAULT_LIMITS,
                )
        return self._client

    async def close(self) -> None:
        """Close the underlying HTTP client. Call on shutdown."""
        if self._client is not None and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    # ---- token storage ----

    def set_tokens(self, telegram_id: int, access_token: str, refresh_token: str | None = None) -> None:
        """Store both access and (optionally) refresh tokens for a player."""
        self._tokens[telegram_id] = access_token
        if refresh_token is not None:
            self._refresh_tokens[telegram_id] = refresh_token

    def get_token(self, telegram_id: int) -> str | None:
        return self._tokens.get(telegram_id)

    def get_refresh_token(self, telegram_id: int) -> str | None:
        return self._refresh_tokens.get(telegram_id)

    def clear_token(self, telegram_id: int) -> None:
        """Remove both access and refresh tokens for a player.

        Call this whenever we know the session is dead: 401 with no refresh,
        refresh failure, /logout, /resetpassword, /cancel during auth flow.
        """
        self._tokens.pop(telegram_id, None)
        self._refresh_tokens.pop(telegram_id, None)

    def _get_refresh_lock(self, telegram_id: int) -> asyncio.Lock:
        lock = self._refresh_locks.get(telegram_id)
        if lock is None:
            lock = asyncio.Lock()
            self._refresh_locks[telegram_id] = lock
        return lock

    # ---- core request ----

    async def _request(
        self,
        method: str,
        path: str,
        *,
        telegram_id: int | None = None,
        token: str | None = None,
        json: dict | None = None,
        timeout: httpx.Timeout | float | None = None,
        _retry_on_401: bool = True,
    ) -> dict[str, Any]:
        headers: dict[str, str] = {}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        elif telegram_id is not None and telegram_id in self._tokens:
            headers["Authorization"] = f"Bearer {self._tokens[telegram_id]}"

        client = await self._get_client()
        request_timeout = timeout if timeout is not None else _DEFAULT_TIMEOUT
        try:
            resp = await client.request(
                method, f"{self.base_url}{path}", headers=headers, json=json,
                timeout=request_timeout,
            )
        except httpx.TimeoutException as exc:
            raise NationCraftError(
                "request timed out — the server may be overloaded. Please try again.",
                code="api_timeout", status_code=504,
            ) from exc
        except httpx.ConnectError as exc:
            raise NationCraftError(
                "cannot reach the game server. Is the API running?",
                code="api_unreachable", status_code=503,
            ) from exc
        except httpx.HTTPError as exc:
            # Other httpx errors (ReadError, RemoteProtocolError, etc.)
            raise NationCraftError(
                f"network error: {exc}",
                code="api_unreachable", status_code=503,
            ) from exc

        body: dict[str, Any]
        try:
            body = resp.json()
        except ValueError:
            # The API returned a non-JSON response — this typically
            # happens when uvicorn returns a 502 Bad Gateway (e.g.
            # because the ASGI app crashed or the event loop is
            # overloaded). Previously the error message was
            # "invalid response: " (with empty resp.text), which was
            # confusing. Now we give a clear, actionable message.
            status = resp.status_code or 502
            if status in (502, 503, 504):
                raise NationCraftError(
                    "the game server is temporarily unavailable (HTTP "
                    f"{status}). Please try again in a moment.",
                    code="api_unreachable", status_code=status,
                ) from None
            raise NationCraftError(
                f"the game server returned an invalid response (HTTP {status}). "
                "Please try again.",
                code="api_error", status_code=status,
            ) from None

        if resp.status_code >= 400 or not body.get("ok"):
            err = body.get("error") or {"code": "http_error", "message": resp.text}

            # ---- 401 handling: evict stale token, attempt refresh, retry once ----
            if resp.status_code == 401 and telegram_id is not None and _retry_on_401:
                # The access token is dead. Drop it so subsequent calls
                # don't keep retrying with the same bad token.
                self._tokens.pop(telegram_id, None)

                refresh_tok = self._refresh_tokens.get(telegram_id)
                if refresh_tok:
                    # Try to refresh and retry the original request once.
                    refreshed = await self._try_refresh(telegram_id, refresh_tok)
                    if refreshed:
                        return await self._request(
                            method, path, telegram_id=telegram_id,
                            json=json, _retry_on_401=False,
                        )
                    # Refresh failed — session is fully dead.
                    self.clear_token(telegram_id)

            raise NationCraftError(
                err.get("message", "API error"),
                code=err.get("code", "api_error"),
                status_code=resp.status_code,
            )
        return body.get("data") or {}

    async def _try_refresh(self, telegram_id: int, refresh_token: str) -> bool:
        """Attempt to rotate tokens via /auth/refresh.

        Returns True on success (new tokens stored), False on any failure
        (session is left cleared by caller).
        """
        lock = self._get_refresh_lock(telegram_id)
        if lock.locked():
            # Another coroutine is already refreshing — wait for it.
            async with lock:
                # If the other coroutine succeeded, we have a new token.
                return telegram_id in self._tokens
        async with lock:
            # Re-check: maybe another coroutine already refreshed while we
            # were waiting to acquire the lock.
            if telegram_id in self._tokens and self._tokens[telegram_id] != refresh_token:
                return True
            try:
                client = await self._get_client()
                resp = await client.post(
                    f"{self.base_url}/auth/refresh",
                    json={"refresh_token": refresh_token},
                )
                if resp.status_code != 200:
                    return False
                data = resp.json().get("data") or {}
                access = data.get("access_token")
                new_refresh = data.get("refresh_token")
                if not access:
                    return False
                self._tokens[telegram_id] = access
                if new_refresh:
                    self._refresh_tokens[telegram_id] = new_refresh
                return True
            except (httpx.HTTPError, ValueError):
                return False

    # ---- auth ----

    async def register(self, telegram_id: int, password: str, username: str | None = None, locale: str = "en") -> dict:
        """Register a new player.

        Adds a single retry on transient network errors (timeout,
        connection reset) before giving up. This is the fix for the
        reported symptom where the bot showed "api_timeout" even
        though the API actually succeeded (200) or returned a
        definitive error (409) — the httpx client's connection was
        stale (half-open TCP) and the FIRST attempt failed, but a
        fresh attempt would have succeeded.

        The retry only fires for transient errors (502/503/504,
        api_timeout, api_unreachable). Definitive errors (401, 409,
        422) are raised immediately without retry.
        """
        last_exc: NationCraftError | None = None
        for attempt in range(2):  # 1 initial + 1 retry
            try:
                data = await self._request("POST", "/auth/register",
                                          json={"telegram_id": telegram_id, "password": password,
                                                "username": username, "locale": locale},
                                          timeout=_AUTH_TIMEOUT)
                break  # success
            except NationCraftError as exc:
                if not is_transient_error(exc):
                    raise  # definitive error — don't retry
                last_exc = exc
                if attempt == 0:
                    await asyncio.sleep(0.3)  # brief backoff before retry
                    continue
                raise  # already retried — give up
        else:
            # Loop exited without break — shouldn't happen, but be safe.
            if last_exc:
                raise last_exc
            raise NationCraftError("register failed", code="api_error", status_code=500)
        # Defensive: if the API returned a valid response but without
        # the expected access_token field, raise a clear error instead
        # of a cryptic KeyError that gets caught by the generic
        # ``except Exception`` handler in the bot.
        access = data.get("access_token")
        if not access:
            raise NationCraftError(
                f"registration succeeded but no access_token in response. "
                f"Response keys: {list(data.keys())}",
                code="api_error", status_code=502,
            )
        self.set_tokens(telegram_id, access, data.get("refresh_token"))
        return data

    async def login(self, telegram_id: int, password: str) -> dict:
        """Login an existing player.

        Same retry-on-transient-error semantics as ``register``.
        """
        last_exc: NationCraftError | None = None
        for attempt in range(2):
            try:
                data = await self._request("POST", "/auth/login",
                                          json={"telegram_id": telegram_id, "password": password},
                                          timeout=_AUTH_TIMEOUT)
                break
            except NationCraftError as exc:
                if not is_transient_error(exc):
                    raise
                last_exc = exc
                if attempt == 0:
                    await asyncio.sleep(0.3)
                    continue
                raise
        else:
            if last_exc:
                raise last_exc
            raise NationCraftError("login failed", code="api_error", status_code=500)
        access = data.get("access_token")
        if not access:
            raise NationCraftError(
                f"login succeeded but no access_token in response. "
                f"Response keys: {list(data.keys())}",
                code="api_error", status_code=502,
            )
        self.set_tokens(telegram_id, access, data.get("refresh_token"))
        return data

    async def logout(self, telegram_id: int) -> None:
        """Revoke the refresh token server-side and clear local state."""
        refresh = self._refresh_tokens.get(telegram_id)
        if refresh:
            try:
                await self._request("POST", "/auth/logout",
                                    json={"refresh_token": refresh},
                                    telegram_id=telegram_id, _retry_on_401=False)
            except NationCraftError:
                pass  # best effort — clear local state regardless
        self.clear_token(telegram_id)

    async def health(self) -> dict[str, Any]:
        """Check API health, using the in-process fast-path when available.

        When the bot and API share one event loop (``--local`` mode),
        we check the API server's running state directly via the
        ``is_serving`` callable (set by ``main.run_all``) instead of
        going through HTTP. This avoids the failure mode where the
        bot blocks the event loop with a slow Telegram send, and the
        HTTP call to /health can't be answered until the loop is free.

        Returns ``{"status": "ok", "source": "in-process"}`` on success
        when in-process mode is active and ``is_serving()`` returns True,
        ``{"status": "ok", "source": "http"}`` on HTTP success, or
        ``{"status": "unreachable"/"timeout"/...}`` on failure.
        """
        # In-process fast path: check via the is_serving callable.
        if _in_process_api:
            try:
                if _is_api_serving is not None and _is_api_serving():
                    return {"status": "ok", "latency_ms": 0, "source": "in-process"}
                # If is_serving is None or returns False, fall through
                # to HTTP. (is_serving=None means main.py didn't supply
                # the callable — we can't tell if the API is up, so we
                # fall back to the HTTP check.)
            except Exception:  # noqa: BLE001
                pass  # fall through to HTTP check

        # HTTP fallback — use a short timeout so /status doesn't block
        # the bot's handler for too long.
        try:
            client = await self._get_client()
            resp = await client.get(
                f"{self.base_url}/health",
                timeout=httpx.Timeout(5.0, connect=2.0, write=2.0, pool=2.0),
            )
            if resp.status_code == 200:
                return {"status": "ok", "latency_ms": 0, "source": "http"}
            return {"status": f"http_{resp.status_code}", "source": "http"}
        except httpx.TimeoutException:
            return {"status": "timeout", "source": "http"}
        except httpx.ConnectError:
            return {"status": "unreachable", "source": "http"}
        except Exception as exc:  # noqa: BLE001
            return {"status": f"error: {type(exc).__name__}", "source": "http"}

    # ---- player profile ----

    async def get_me(self, telegram_id: int) -> dict | None:
        """Return the current player's profile (locale, role, etc.).

        Returns the player dict on success. Returns None on:
        - Network errors (api_unreachable, api_timeout) — the token is
          PRESERVED because the API might just be slow/unreachable.
        - Auth errors (401, token expired/revoked) — the token is
          already evicted by ``_request`` (and refresh is attempted).

        Callers should NOT clear the local token just because
        ``get_me`` returned None — that would log the user out on every
        transient network blip. Use ``get_token`` to check if the
        token is still present (it'll be None if auth failed, present
        if only a network error occurred).
        """
        try:
            return await self._request("GET", "/auth/me", telegram_id=telegram_id)
        except NationCraftError:
            # If it was a 401, _request already evicted the token (and
            # attempted refresh). If it was a network/timeout error,
            # the token is still in self._tokens.
            return None
        except Exception:  # noqa: BLE001
            return None

    async def set_locale(self, telegram_id: int, locale: str) -> dict:
        """Update the player's preferred locale."""
        return await self._request(
            "POST", "/auth/locale", telegram_id=telegram_id, json={"locale": locale}
        )

    async def reset_password(
        self, telegram_id: int, old_password: str, new_password: str
    ) -> dict:
        """Reset the player's password. Requires the old password."""
        return await self._request(
            "POST", "/auth/reset-password", telegram_id=telegram_id,
            json={
                "telegram_id": telegram_id,
                "old_password": old_password,
                "new_password": new_password,
            },
        )

    async def promote_admin(self, caller_telegram_id: int, target_telegram_id: int, role: str = "admin") -> dict:
        """Promote a player to admin/owner. Caller must be owner or telegram admin."""
        return await self._request(
            "POST", "/auth/promote-admin", telegram_id=caller_telegram_id,
            json={"telegram_id": target_telegram_id, "role": role},
        )

    # ---- worlds & countries ----

    async def list_worlds(self, telegram_id: int) -> list[dict]:
        return await self._request("GET", "/worlds", telegram_id=telegram_id) or []

    async def list_available_countries(self, telegram_id: int, world_id: int) -> list[dict]:
        return await self._request("GET", f"/countries/available/{world_id}", telegram_id=telegram_id) or []

    async def select_country(self, telegram_id: int, world_id: int, code: str) -> dict:
        return await self._request("POST", "/countries/select", telegram_id=telegram_id,
                                  json={"world_id": world_id, "country_code": code})

    async def my_country(self, telegram_id: int) -> dict | None:
        return await self._request("GET", "/countries/me", telegram_id=telegram_id)

    # ---- production ----

    async def list_buildings(self, telegram_id: int) -> list[dict]:
        return await self._request("GET", "/production/buildings", telegram_id=telegram_id) or []

    async def build(self, telegram_id: int, key: str, count: int = 1) -> dict:
        return await self._request("POST", "/production/build", telegram_id=telegram_id,
                                  json={"building_key": key, "count": count})

    async def research(self, telegram_id: int, tech_key: str) -> dict:
        return await self._request("POST", "/production/research", telegram_id=telegram_id,
                                  json={"tech_key": tech_key})

    # ---- military ----

    async def list_units(self, telegram_id: int) -> list[dict]:
        return await self._request("GET", "/military/units", telegram_id=telegram_id) or []

    async def train(self, telegram_id: int, unit_key: str, count: int) -> dict:
        return await self._request("POST", "/military/train", telegram_id=telegram_id,
                                  json={"unit_key": unit_key, "count": count})

    async def list_wars(self, telegram_id: int) -> list[dict]:
        return await self._request("GET", "/military/wars", telegram_id=telegram_id) or []

    # ---- market ----

    async def list_orders(self, telegram_id: int) -> list[dict]:
        return await self._request("GET", "/market/orders", telegram_id=telegram_id) or []

    async def place_order(self, telegram_id: int, side: str, resource_key: str, qty: float, price: float) -> dict:
        return await self._request("POST", "/market/order", telegram_id=telegram_id,
                                  json={"side": side, "resource_key": resource_key,
                                        "quantity": qty, "unit_price": price})

    # ---- social ----

    async def list_missions(self, telegram_id: int) -> list[dict]:
        return await self._request("GET", "/social/missions", telegram_id=telegram_id) or []

    async def claim_mission(self, telegram_id: int, mission_id: int) -> dict:
        return await self._request("POST", "/social/mission/claim", telegram_id=telegram_id,
                                  json={"mission_id": mission_id})

    async def list_notifications(self, telegram_id: int, limit: int = 20) -> list[dict]:
        return await self._request("GET", f"/social/notifications?limit={limit}", telegram_id=telegram_id) or []

    async def rankings(self, telegram_id: int, world_id: int, metric: str = "population") -> list[dict]:
        return await self._request("GET", f"/social/rankings/{world_id}?metric={metric}", telegram_id=telegram_id) or []


api_client = ApiClient()
