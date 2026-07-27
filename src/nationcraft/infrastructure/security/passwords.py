"""Password hashing using Argon2id (RFC 9106)."""
from __future__ import annotations

from abc import ABC, abstractmethod

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
    """Argon2id hasher with parameters from settings."""

    def __init__(self) -> None:
        self._ph = _Argon2PasswordHasher(
            time_cost=settings.ARGON2_ITERATIONS,
            memory_cost=settings.ARGON2_MEMORY_KIB,
            parallelism=settings.ARGON2_PARALLELISM,
            type=Argon2Type.ID,
        )

    def hash(self, plain: str) -> str:
        return self._ph.hash(plain)

    def verify(self, plain: str, hashed: str) -> bool:
        try:
            return self._ph.verify(hashed, plain)
        except VerifyMismatchError as exc:
            raise AuthenticationError("invalid credentials") from exc


default_hasher = Argon2PasswordHasher()
