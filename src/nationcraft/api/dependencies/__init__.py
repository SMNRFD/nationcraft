"""API dependencies: DB session, current player, rate limiter."""
from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Header, Request
from sqlalchemy.ext.asyncio import AsyncSession

from nationcraft.core.config import settings
from nationcraft.core.exceptions import AuthenticationError, RateLimitError
from nationcraft.infrastructure.db.session import AsyncSessionLocal
from nationcraft.infrastructure.security import VerifyToken
from nationcraft.infrastructure.security.rate_limit import (
    InMemoryRateLimiter,
    RedisRateLimiter,
    RateLimiter,
)

# Lazy singletons
_limiter: RateLimiter | None = None


async def get_session() -> AsyncSession:
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


SessionDep = Annotated[AsyncSession, Depends(get_session)]


def get_rate_limiter() -> RateLimiter:
    global _limiter
    if _limiter is None:
        from nationcraft.infrastructure.cache import cache
        if cache.enabled:
            try:
                _limiter = RedisRateLimiter(cache._redis)
            except Exception:  # noqa: BLE001
                _limiter = InMemoryRateLimiter()
        else:
            _limiter = InMemoryRateLimiter()
    return _limiter


async def current_player_id(
    authorization: Annotated[str | None, Header()] = None,
    x_api_token: Annotated[str | None, Header()] = None,
) -> int:
    """Resolve and validate the JWT, returning the player id."""
    token = None
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization[7:]
    elif x_api_token:
        token = x_api_token
    if not token:
        raise AuthenticationError("missing token")
    payload = VerifyToken()(token, expected_type="access")
    return int(payload["sub"])


CurrentPlayer = Annotated[int, Depends(current_player_id)]


async def rate_limit(
    request: Request,
    player_id: Annotated[int, Depends(current_player_id)],
    limiter: RateLimiter = Depends(get_rate_limiter),
) -> None:
    key = f"api:{player_id}:{request.url.path}"
    await limiter.check(key, settings.RATE_LIMIT_API_PER_MINUTE, 60)
