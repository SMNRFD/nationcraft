"""Integration tests for password reset and admin promotion."""
from __future__ import annotations

import pytest

from nationcraft.application.dto.auth import (
    LoginRequest,
    RegisterRequest,
    ResetPasswordRequest,
)
from nationcraft.application.services import AuthService
from nationcraft.core.exceptions import AuthenticationError, ValidationError
from nationcraft.infrastructure.db.models import PlayerModel


@pytest.mark.asyncio
async def test_reset_password(session) -> None:
    svc = AuthService(session)
    await svc.register(RegisterRequest(telegram_id=100, password="old-pass-123"))
    await session.commit()

    # Reset password.
    await svc.reset_password(100, "old-pass-123", "new-pass-456")
    await session.commit()

    # Old password no longer works.
    with pytest.raises(AuthenticationError):
        await svc.login(LoginRequest(telegram_id=100, password="old-pass-123"))

    # New password works.
    await svc.login(LoginRequest(telegram_id=100, password="new-pass-456"))


@pytest.mark.asyncio
async def test_reset_password_wrong_old(session) -> None:
    svc = AuthService(session)
    await svc.register(RegisterRequest(telegram_id=101, password="correct-old"))
    await session.commit()

    with pytest.raises(AuthenticationError):
        await svc.reset_password(101, "wrong-old", "new-pass-789")


@pytest.mark.asyncio
async def test_promote_to_admin(session) -> None:
    svc = AuthService(session)
    await svc.register(RegisterRequest(telegram_id=102, password="password123"))
    await session.commit()

    player = await svc.promote_to_admin(102, role="admin")
    assert player.role == "admin"

    # Verify persisted.
    from sqlalchemy import select
    p = await session.scalar(select(PlayerModel).where(PlayerModel.telegram_id == 102))
    assert p.role == "admin"


@pytest.mark.asyncio
async def test_promote_invalid_role(session) -> None:
    svc = AuthService(session)
    await svc.register(RegisterRequest(telegram_id=103, password="password123"))
    await session.commit()

    with pytest.raises(ValidationError):
        await svc.promote_to_admin(103, role="superuser")


@pytest.mark.asyncio
async def test_multi_admin_ids_parse() -> None:
    """Verify that TELEGRAM_ADMIN_IDS with multiple comma-separated IDs parses correctly."""
    import os
    os.environ["TELEGRAM_ADMIN_IDS"] = "111,222,333"
    # Reload settings.
    from nationcraft.core.config import Settings
    s = Settings()
    assert s.admin_ids == {111, 222, 333}
    assert 222 in s.admin_ids
    assert 999 not in s.admin_ids
