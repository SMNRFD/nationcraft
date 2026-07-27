"""Bot API client — thin HTTP wrapper around the FastAPI backend."""
from __future__ import annotations

from typing import Any

import httpx

from nationcraft.core.config import settings
from nationcraft.core.exceptions import NationCraftError, AuthenticationError


class ApiClient:
    """Wraps REST calls to the backend, with auto token handling."""

    def __init__(self, base_url: str | None = None) -> None:
        self.base_url = (base_url or settings.API_BASE_URL).rstrip("/")
        self._tokens: dict[int, str] = {}  # telegram_id -> access_token

    async def _request(
        self, method: str, path: str, *, telegram_id: int | None = None,
        token: str | None = None, json: dict | None = None,
    ) -> dict[str, Any]:
        headers: dict[str, str] = {}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        elif telegram_id is not None and telegram_id in self._tokens:
            headers["Authorization"] = f"Bearer {self._tokens[telegram_id]}"
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.request(method, f"{self.base_url}{path}", headers=headers, json=json)
        body: dict[str, Any]
        try:
            body = resp.json()
        except ValueError:
            raise NationCraftError(f"invalid response: {resp.text}")
        if resp.status_code >= 400 or not body.get("ok"):
            err = body.get("error") or {"code": "http_error", "message": resp.text}
            raise NationCraftError(
                err.get("message", "API error"), code=err.get("code", "api_error"),
                status_code=resp.status_code,
            )
        return body.get("data") or {}

    # ---- auth ----
    async def register(self, telegram_id: int, password: str, username: str | None = None, locale: str = "en") -> dict:
        data = await self._request("POST", "/auth/register",
                                    json={"telegram_id": telegram_id, "password": password,
                                          "username": username, "locale": locale})
        self._tokens[telegram_id] = data["access_token"]
        return data

    async def login(self, telegram_id: int, password: str) -> dict:
        data = await self._request("POST", "/auth/login",
                                    json={"telegram_id": telegram_id, "password": password})
        self._tokens[telegram_id] = data["access_token"]
        return data

    def set_token(self, telegram_id: int, token: str) -> None:
        self._tokens[telegram_id] = token

    def get_token(self, telegram_id: int) -> str | None:
        return self._tokens.get(telegram_id)

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
