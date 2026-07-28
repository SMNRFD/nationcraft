"""Password hashing using Argon2id (RFC 9106).

All hashing/verification runs in a thread executor so the async event
loop is NOT blocked. This is critical when the API and bot share a
single process — without this, Argon2's ~200ms CPU-bound operation
would freeze the entire event loop, causing httpx timeouts.
"""
from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from functools import partial

from argon2 import PasswordHasher as _Argon2PasswordHasher, Type as Argon2Type
from argon2.exceptions import VerifyMismatchError

from nationcraft.core.config import settings
from nationcraft.core.exceptions import AuthenticationError


class PasswordHasher(ABC):
    """Abstract password hasher interface."""

    @abstractmethod
    def hash(self, plain: str) -> str: ...

    @abstractmethod
    def verify(self, plain: str, hashed: str) -> bool: ...


class Argon2PasswordHasher(PasswordHasher):
    """Argon2id hasher with parameters from settings.

    The synchronous ``_hash_sync`` and ``_verify_sync`` methods are
    wrapped in ``asyncio.to_thread`` so they don't block the event loop.
    """

    def __init__(self) -> None:
        self._ph = _Argon2PasswordHasher(
            time_cost=settings.ARGON2_ITERATIONS,
            memory_cost=settings.ARGON2_MEMORY_KIB,
            parallelism=settings.ARGON2_PARALLELISM,
            type=Argon2Type.ID,
        )

    def _hash_sync(self, plain: str) -> str:
        return self._ph.hash(plain)

    def _verify_sync(self, plain: str, hashed: str) -> bool:
        try:
            return self._ph.verify(hashed, plain)
        except VerifyMismatchError as exc:
            raise AuthenticationError("invalid credentials") from exc

    def hash(self, plain: str) -> str:
        """Synchronous hash (use only in non-async contexts)."""
        return self._hash_sync(plain)

    def verify(self, plain: str, hashed: str) -> bool:
        """Synchronous verify (use only in non-async contexts)."""
        return self._verify_sync(plain, hashed)

    async def hash_async(self, plain: str) -> str:
        """Async hash — runs in a thread executor to avoid blocking the event loop."""
        return await asyncio.to_thread(self._hash_sync, plain)

    async def verify_async(self, plain: str, hashed: str) -> bool:
        """Async verify — runs in a thread executor to avoid blocking the event loop."""
        return await asyncio.to_thread(self._verify_sync, plain, hashed)


default_hasher = Argon2PasswordHasher()
