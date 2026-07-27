"""Player repository."""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from nationcraft.domain.entities import Player
from nationcraft.domain.enums import PlayerRole
from nationcraft.infrastructure.db.models import PlayerModel


class PlayerRepository:
    """SQLAlchemy implementation of :class:`IPlayerRepository`."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, player_id: int) -> Player | None:
        m = await self.session.get(PlayerModel, player_id)
        return self._to_entity(m) if m else None

    async def get_by_telegram(self, telegram_id: int) -> Player | None:
        stmt = select(PlayerModel).where(PlayerModel.telegram_id == telegram_id)
        m = (await self.session.execute(stmt)).scalar_one_or_none()
        return self._to_entity(m) if m else None

    async def list_by_world(self, world_id: int) -> list[Player]:
        stmt = select(PlayerModel).where(PlayerModel.world_id == world_id)
        rows = (await self.session.execute(stmt)).scalars().all()
        return [self._to_entity(m) for m in rows]

    async def create(self, **kwargs: object) -> Player:
        m = PlayerModel(**kwargs)  # type: ignore[arg-type]
        self.session.add(m)
        await self.session.flush()
        return self._to_entity(m)

    async def update(self, player: Player) -> Player:
        stmt = (
            update(PlayerModel)
            .where(PlayerModel.id == player.id)
            .values(
                username=player.username,
                locale=player.locale,
                role=player.role.value,
                is_banned=player.is_banned,
                last_login_at=player.last_login_at,
                world_id=player.world_id,
                country_id=player.country_id,
            )
            .returning(PlayerModel)
        )
        m = (await self.session.execute(stmt)).scalar_one()
        return self._to_entity(m)

    async def ban(self, player_id: int) -> bool:
        stmt = update(PlayerModel).where(PlayerModel.id == player_id).values(is_banned=True)
        await self.session.execute(stmt)
        return True

    async def touch_login(self, player_id: int) -> None:
        stmt = (
            update(PlayerModel)
            .where(PlayerModel.id == player_id)
            .values(last_login_at=datetime.now(timezone.utc))
        )
        await self.session.execute(stmt)

    @staticmethod
    def _to_entity(m: PlayerModel) -> Player:
        return Player(
            id=m.id,
            telegram_id=m.telegram_id,
            username=m.username,
            locale=m.locale,
            role=PlayerRole(m.role),
            is_banned=m.is_banned,
            created_at=m.created_at,
            last_login_at=m.last_login_at,
            world_id=m.world_id,
            country_id=m.country_id,
        )
