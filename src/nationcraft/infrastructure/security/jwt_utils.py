"""JWT utilities (access + refresh tokens, signed with HS256).

Important design notes
---------------------
* The dataclass defaults use ``field(default_factory=...)`` instead of a
  frozen ``= settings.SECRET_KEY`` value. This ensures the JWT issuer and
  verifier always pick up the *current* settings value when instantiated,
  not the value frozen at module import time. Previously, if settings
  were reloaded after import (e.g., by an admin endpoint that rotates
  SECRET_KEY), the issuer would use the old secret and the verifier the
  new secret — every token would fail verification.

* ``VerifyToken.__call__`` adds a 5-second ``leeway`` to ``jwt.decode``.
  This tolerates small clock skew between the issuing host and the
  verifying host (important in the docker-compose deployment where the
  ``api`` and ``worker`` containers may have slight NTP drift) and also
  tolerates the ``iat`` (issued-at) claim being a second in the future,
  which can happen when the JWT is issued in the same second that
  PyJWT's ``verify_iat`` check runs.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

import jwt
from jwt import InvalidTokenError

from nationcraft.core.config import settings
from nationcraft.core.exceptions import AuthenticationError


# Clock-skew tolerance for JWT verification (seconds). PyJWT applies this
# to both ``exp`` (expiry) and ``iat`` (issued-at) claims.
_JWT_LEEWAY_SECONDS = 5


@dataclass(slots=True)
class TokenPair:
    access_token: str
    refresh_token: str
    access_expires_at: datetime
    refresh_expires_at: datetime
    token_type: str = "Bearer"


@dataclass(slots=True)
class IssueTokens:
    """Service that issues access + refresh JWT pairs.

    All defaults read from ``settings`` lazily so changes to settings
    (e.g., via ``--local`` overrides or admin rotation) are picked up
    when a new ``IssueTokens()`` instance is constructed.
    """

    secret: str = field(default_factory=lambda: settings.SECRET_KEY)
    issuer: str = field(default_factory=lambda: settings.JWT_ISSUER)
    access_ttl: int = field(default_factory=lambda: settings.JWT_ACCESS_TTL_SECONDS)
    refresh_ttl: int = field(default_factory=lambda: settings.JWT_REFRESH_TTL_SECONDS)

    def for_player(self, player_id: int, *, role: str = "player", scopes: list[str] | None = None) -> TokenPair:
        now = datetime.now(timezone.utc)
        access_jti = str(uuid.uuid4())
        access_payload = {
            "sub": str(player_id),
            "role": role,
            "scopes": scopes or [],
            "iss": self.issuer,
            "iat": int(now.timestamp()),
            "exp": int((now + timedelta(seconds=self.access_ttl)).timestamp()),
            "jti": access_jti,
            "type": "access",
        }
        refresh_jti = str(uuid.uuid4())
        refresh_payload = {
            "sub": str(player_id),
            "iss": self.issuer,
            "iat": int(now.timestamp()),
            "exp": int((now + timedelta(seconds=self.refresh_ttl)).timestamp()),
            "jti": refresh_jti,
            "type": "refresh",
        }
        access = jwt.encode(access_payload, self.secret, algorithm="HS256")
        refresh = jwt.encode(refresh_payload, self.secret, algorithm="HS256")
        return TokenPair(
            access_token=access,
            refresh_token=refresh,
            access_expires_at=now + timedelta(seconds=self.access_ttl),
            refresh_expires_at=now + timedelta(seconds=self.refresh_ttl),
        )


@dataclass(slots=True)
class VerifyToken:
    """Service that verifies a JWT and returns its payload.

    Same default-factory pattern as ``IssueTokens`` to keep the secret
    in sync with the live settings.
    """

    secret: str = field(default_factory=lambda: settings.SECRET_KEY)
    issuer: str = field(default_factory=lambda: settings.JWT_ISSUER)

    def __call__(self, token: str, *, expected_type: str | None = None) -> dict[str, Any]:
        try:
            payload = jwt.decode(
                token,
                self.secret,
                algorithms=["HS256"],
                issuer=self.issuer,
                leeway=_JWT_LEEWAY_SECONDS,
            )
        except InvalidTokenError as exc:
            raise AuthenticationError("invalid token") from exc
        if expected_type and payload.get("type") != expected_type:
            raise AuthenticationError("wrong token type")
        return payload


def create_access_token(player_id: int, **kwargs: Any) -> str:
    pair = IssueTokens().for_player(player_id, **kwargs)
    return pair.access_token


def create_refresh_token(player_id: int, **kwargs: Any) -> str:
    pair = IssueTokens().for_player(player_id, **kwargs)
    return pair.refresh_token


def decode_token(token: str, *, expected_type: str | None = None) -> dict[str, Any]:
    return VerifyToken()(token, expected_type=expected_type)
