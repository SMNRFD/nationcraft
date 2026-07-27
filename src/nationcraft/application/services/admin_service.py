"""Admin service: broadcast, ban, manage plugins."""
from __future__ import annotations

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from nationcraft.application.services.notification_service import NotificationService
from nationcraft.core.exceptions import NotFoundError
from nationcraft.domain.enums import NotificationLevel
from nationcraft.infrastructure.db.models import PlayerModel, PluginStateModel


class AdminService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.notif = NotificationService(session)

    async def broadcast(self, message: str, locale: str | None = None) -> int:
        stmt = select(PlayerModel).where(PlayerModel.is_banned.is_(False))
        if locale:
            stmt = stmt.where(PlayerModel.locale == locale)
        rows = (await self.session.execute(stmt)).scalars().all()
        for p in rows:
            await self.notif.notify(
                player_id=p.id, level=NotificationLevel.INFO,
                title="Broadcast", body=message,
            )
        return len(rows)

    async def ban_player(self, player_id: int) -> bool:
        p = await self.session.get(PlayerModel, player_id)
        if p is None:
            raise NotFoundError("player not found")
        p.is_banned = True
        await self.session.flush()
        return True

    async def unban_player(self, player_id: int) -> bool:
        p = await self.session.get(PlayerModel, player_id)
        if p is None:
            raise NotFoundError("player not found")
        p.is_banned = False
        await self.session.flush()
        return True

    async def set_plugin_enabled(self, plugin_id: str, enabled: bool) -> None:
        existing = await self.session.scalar(
            select(PluginStateModel).where(PluginStateModel.plugin_id == plugin_id)
        )
        if existing is None:
            self.session.add(PluginStateModel(plugin_id=plugin_id, enabled=enabled))
        else:
            existing.enabled = enabled
        await self.session.flush()
