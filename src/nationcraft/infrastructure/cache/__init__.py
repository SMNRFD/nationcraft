"""Redis cache layer.

The connection is configured with bounded socket timeouts so that a
hung Redis cannot block the API startup or the request path indefinitely.
Previously, no socket timeouts were set — meaning a Redis process that
accepted TCP but didn't respond to commands could hang the bot forever.
"""
from __future__ import annotations

import json
from typing import Any

import redis.asyncio as aioredis
from redis.exceptions import ConnectionError as RedisConnectionError, TimeoutError as RedisTimeoutError

from nationcraft.core.config import settings


class RedisCache:
    """Thin async wrapper around redis.asyncio with JSON serialization.

    All operations are bounded by ``socket_connect_timeout=2.0`` and
    ``socket_timeout=2.0`` so a hung Redis cannot stall the event loop.
    """

    def __init__(self, url: str | None = None) -> None:
        self._redis = aioredis.from_url(
            url or settings.REDIS_URL,
            decode_responses=True,
            socket_connect_timeout=2.0,
            socket_timeout=2.0,
            retry_on_timeout=True,
            retry_on_error=[RedisConnectionError, RedisTimeoutError],
        )

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
