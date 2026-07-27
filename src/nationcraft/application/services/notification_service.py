"""Notification service: create, list, mark read, fan-out via event bus."""
from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from nationcraft.core.events import Event, event_bus
from nationcraft.domain.enums import NotificationLevel
from nationcraft.infrastructure.repositories import NotificationRepository


class NotificationService:
    def __init__(self, session: AsyncSession) -> None:
        self.repo = NotificationRepository(session)

    async def notify(
        self,
        *,
        player_id: int,
        level: NotificationLevel | str = NotificationLevel.INFO,
        title: str,
        body: str = "",
        data: dict | None = None,
    ) -> None:
        level_val = level.value if isinstance(level, NotificationLevel) else level
        await self.repo.create(
            player_id=player_id, level=level_val, title=title, body=body,
            data=data or {},
        )
        await event_bus.publish(Event(
            type="notification.queued", player_id=player_id,
            payload={"level": level_val, "title": title},
        ))

    async def list_for_player(self, player_id: int, limit: int = 50):
        return await self.repo.list_by_player(player_id, limit=limit)

    async def mark_read(self, notification_id: int) -> bool:
        return await self.repo.mark_read(notification_id)
