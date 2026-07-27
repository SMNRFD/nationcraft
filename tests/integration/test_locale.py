"""Integration tests for the locale update endpoint."""
from __future__ import annotations

import pytest

from nationcraft.application.dto.auth import RegisterRequest, UpdateLocaleRequest
from nationcraft.application.services import AuthService
from nationcraft.core.exceptions import ValidationError
from nationcraft.infrastructure.db.models import PlayerModel


@pytest.mark.asyncio
async def test_set_locale_persists(session) -> None:
    svc = AuthService(session)
    await svc.register(RegisterRequest(telegram_id=1, password="password123", locale="en"))
    await session.commit()

    player = await svc.set_locale(player_id=1, locale="fa")
    assert player.locale == "fa"

    # Verify it's persisted.
    p = await session.get(PlayerModel, 1)
    assert p.locale == "fa"


@pytest.mark.asyncio
async def test_set_locale_rejects_unsupported(session) -> None:
    svc = AuthService(session)
    await svc.register(RegisterRequest(telegram_id=2, password="password123", locale="en"))
    await session.commit()

    with pytest.raises(ValidationError):
        await svc.set_locale(player_id=2, locale="zh")


@pytest.mark.asyncio
async def test_get_player_returns_locale(session) -> None:
    svc = AuthService(session)
    resp = await svc.register(RegisterRequest(telegram_id=3, password="password123", locale="fa"))
    await session.commit()

    player = await svc.get_player(player_id=resp.player.id)
    assert player.locale == "fa"
    assert player.telegram_id == 3
