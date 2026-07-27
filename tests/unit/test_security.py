"""Unit tests for JWT utilities and password hashing."""
from __future__ import annotations

import pytest

from nationcraft.core.exceptions import AuthenticationError
from nationcraft.infrastructure.security import (
    Argon2PasswordHasher,
    IssueTokens,
    VerifyToken,
)


def test_argon2_hash_and_verify() -> None:
    h = Argon2PasswordHasher()
    hashed = h.hash("s3cret-password")
    assert h.verify("s3cret-password", hashed) is True
    with pytest.raises(AuthenticationError):
        h.verify("wrong", hashed)


def test_jwt_issue_and_verify() -> None:
    issuer = IssueTokens(secret="test", issuer="nc-test")
    pair = issuer.for_player(player_id=42, role="admin")
    payload = VerifyToken(secret="test", issuer="nc-test")(pair.access_token, expected_type="access")
    assert payload["sub"] == "42"
    assert payload["role"] == "admin"


def test_jwt_rejects_wrong_type() -> None:
    issuer = IssueTokens(secret="test", issuer="nc-test")
    pair = issuer.for_player(player_id=1)
    with pytest.raises(AuthenticationError):
        VerifyToken(secret="test", issuer="nc-test")(pair.access_token, expected_type="refresh")


def test_jwt_rejects_bad_token() -> None:
    with pytest.raises(AuthenticationError):
        VerifyToken(secret="test", issuer="nc-test")("not-a-jwt")
