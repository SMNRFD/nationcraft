"""Redis cache layer."""
from __future__ import annotations

import json
from typing import Any

import redis.asyncio as aioredis

from nationcraft.core.config import settings


class RedisCache:
    """Thin async wrapper around redis.asyncio with JSON serialization."""

    def __init__(self, url: str | None = None) -> None:
        self._redis = aioredis.from_url(url or settings.REDIS_URL, decode_responses=True)

    async def get(self, key: str) -> Any | None:
        raw = await self._redis.get(key)
        if raw is None:
            return None
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return raw

    async def set(self, key: str, value: Any, ttl: int | None = None) -> None:
        data = json.dumps(value, default=str)
        if ttl:
            await self._redis.set(key, data, ex=ttl)
        else:
            await self._redis.set(key, data)

    async def delete(self, *keys: str) -> int:
        return await self._redis.delete(*keys)

    async def incr(self, key: str, *, ttl: int | None = None) -> int:
        v = await self._redis.incr(key)
        if v == 1 and ttl:
            await self._redis.expire(key, ttl)
        return v

    async def publish(self, channel: str, message: Any) -> int:
        return await self._redis.publish(channel, json.dumps(message, default=str))

    async def close(self) -> None:
        await self._redis.close()


cache = RedisCache()
