"""Bot API client — thin HTTP wrapper around the FastAPI backend.

Key design choices
------------------
* Single shared ``httpx.AsyncClient`` with a tight timeout (5s read, 2s connect).
  The previous 15s timeout was the direct cause of the reported 15-17s update
  durations: every hung API call blocked the bot's per-chat dispatcher for
  15s, which made aiogram queue all subsequent updates for that chat —
  producing the "Please send your password" prompt appearing AFTER the
  timeout error.
* Stale tokens are evicted on every 401. Previously a single 401 left a dead
  token in ``self._tokens`` forever, so every subsequent call failed and the
  user had to type /login again to recover.
* Automatic refresh-token rotation: when a 401 is received AND we have a
  refresh token stored, the client transparently calls /auth/refresh, stores
  the new pair, and retries the original request once. This eliminates the
  15-minute cliff caused by JWT_ACCESS_TTL_SECONDS=900 with no refresh flow.
* Refresh failures invalidate the local session (both tokens removed).
"""
from __future__ import annotations

import asyncio
from typing import Any

import httpx

from nationcraft.core.config import settings
from nationcraft.core.exceptions import NationCraftError, AuthenticationError


# Timeout: 15s read (was 5s — too short for Argon2 hashing on Windows/
# Python 3.11 where it can take 500ms+; combined with DB I/O the total
# can exceed 5s, causing httpx.ReadTimeout → "request timed out").
# 2s connect (DNS+TCP), 5s write, 2s pool.
_DEFAULT_TIMEOUT = httpx.Timeout(15.0, connect=2.0, write=5.0, pool=2.0)
_DEFAULT_LIMITS = httpx.Limits(max_connections=30, max_keepalive_connections=15)


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
        _retry_on_401: bool = True,
    ) -> dict[str, Any]:
        headers: dict[str, str] = {}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        elif telegram_id is not None and telegram_id in self._tokens:
            headers["Authorization"] = f"Bearer {self._tokens[telegram_id]}"

        client = await self._get_client()
        try:
            resp = await client.request(
                method, f"{self.base_url}{path}", headers=headers, json=json
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
        data = await self._request("POST", "/auth/register",
                                  json={"telegram_id": telegram_id, "password": password,
                                        "username": username, "locale": locale})
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
        data = await self._request("POST", "/auth/login",
                                  json={"telegram_id": telegram_id, "password": password})
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
