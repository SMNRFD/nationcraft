"""Rate limiting via Redis (sliding window) with in-memory fallback for tests."""
from __future__ import annotations

import time
from abc import ABC, abstractmethod
from collections import defaultdict

from nationcraft.core.exceptions import RateLimitError


class RateLimiter(ABC):
    @abstractmethod
    async def check(self, key: str, limit: int, window_seconds: int) -> bool: ...


class InMemoryRateLimiter(RateLimiter):
    def __init__(self) -> None:
        self._hits: dict[str, list[float]] = defaultdict(list)

    async def check(self, key: str, limit: int, window_seconds: int) -> bool:
        now = time.time()
        cutoff = now - window_seconds
        hits = [t for t in self._hits[key] if t > cutoff]
        if len(hits) >= limit:
            raise RateLimitError(
                f"rate limit exceeded for {key}: {limit}/{window_seconds}s",
                code="rate_limited",
            )
        hits.append(now)
        self._hits[key] = hits
        return True


class RedisRateLimiter(RateLimiter):
    """Sliding window rate limiter backed by Redis sorted sets."""

    def __init__(self, redis) -> None:  # type: ignore[no-untyped-def]
        self.redis = redis

    async def check(self, key: str, limit: int, window_seconds: int) -> bool:
        now = time.time()
        cutoff = now - window_seconds
        redis_key = f"ratelimit:{key}"
        pipe = self.redis.pipeline()
        pipe.zremrangebyscore(redis_key, 0, cutoff)
        pipe.zadd(redis_key, {str(now): now})
        pipe.zcard(redis_key)
        pipe.expire(redis_key, window_seconds)
        results = await pipe.execute()
        count = results[2]
        if count > limit:
            raise RateLimitError(f"rate limit exceeded for {key}", code="rate_limited")
        return True
