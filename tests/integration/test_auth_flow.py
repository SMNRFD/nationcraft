"""Integration tests for the AuthService against an in-memory SQLite DB."""
from __future__ import annotations

import pytest

from nationcraft.application.dto.auth import LoginRequest, RegisterRequest
from nationcraft.application.services import AuthService
from nationcraft.core.exceptions import AuthenticationError, ConflictError


@pytest.mark.asyncio
async def test_register_and_login(session) -> None:
    svc = AuthService(session)
    await svc.register(RegisterRequest(telegram_id=1, password="password123", username="alice"))
    await session.commit()

    # Login with correct password.
    data = await svc.login(LoginRequest(telegram_id=1, password="password123"))
    assert data.player.telegram_id == 1
    assert data.access_token


@pytest.mark.asyncio
async def test_register_conflict(session) -> None:
    svc = AuthService(session)
    await svc.register(RegisterRequest(telegram_id=2, password="password123"))
    await session.commit()
    with pytest.raises(ConflictError):
        await svc.register(RegisterRequest(telegram_id=2, password="password123"))


@pytest.mark.asyncio
async def test_login_wrong_password(session) -> None:
    svc = AuthService(session)
    await svc.register(RegisterRequest(telegram_id=3, password="password123"))
    await session.commit()
    with pytest.raises(AuthenticationError):
        await svc.login(LoginRequest(telegram_id=3, password="wrong"))
