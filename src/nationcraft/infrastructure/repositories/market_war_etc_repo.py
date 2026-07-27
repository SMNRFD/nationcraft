"""Market, war, diplomacy, alliance, mission, notification, event, order repositories."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from nationcraft.domain.entities import (
    Alliance,
    AllianceMember,
    Diplomacy,
    GameEvent,
    MarketOrder,
    Mission,
    Notification,
    Order,
    War,
)
from nationcraft.domain.enums import (
    AllianceRole,
    DiplomaticStatus,
    MarketOrderSide,
    MarketOrderStatus,
    MissionStatus,
    NotificationLevel,
    OrderType,
    WarStatus,
)
from nationcraft.infrastructure.db.models import (
    AllianceMemberModel,
    AllianceModel,
    BattleModel,
    DiplomacyModel,
    GameEventModel,
    MarketOrderModel,
    MarketTradeModel,
    MissionModel,
    NotificationModel,
    OrderQueueModel,
    WarModel,
)


# ----------------------------- Market -----------------------------

class MarketRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_open_orders(self, world_id: int) -> list[MarketOrder]:
        stmt = select(MarketOrderModel).where(
            MarketOrderModel.world_id == world_id,
            MarketOrderModel.status.in_([MarketOrderStatus.OPEN.value, MarketOrderStatus.PARTIAL.value]),
        )
        rows = (await self.session.execute(stmt)).scalars().all()
        return [self._to_entity(m) for m in rows]

    async def list_by_country(self, country_id: int) -> list[MarketOrder]:
        stmt = select(MarketOrderModel).where(MarketOrderModel.country_id == country_id)
        rows = (await self.session.execute(stmt)).scalars().all()
        return [self._to_entity(m) for m in rows]

    async def matching_orders(
        self, world_id: int, side: MarketOrderSide, resource: str
    ) -> list[MarketOrder]:
        opposite = MarketOrderSide.BUY if side == MarketOrderSide.SELL else MarketOrderSide.SELL
        stmt = select(MarketOrderModel).where(
            MarketOrderModel.world_id == world_id,
            MarketOrderModel.resource_key == resource,
            MarketOrderModel.side == opposite.value,
            MarketOrderModel.status.in_([MarketOrderStatus.OPEN.value, MarketOrderStatus.PARTIAL.value]),
        ).order_by(
            MarketOrderModel.unit_price.asc() if side == MarketOrderSide.BUY
            else MarketOrderModel.unit_price.desc(),
            MarketOrderModel.created_at.asc(),
        )
        rows = (await self.session.execute(stmt)).scalars().all()
        return [self._to_entity(m) for m in rows]

    async def create(self, **kwargs: object) -> MarketOrder:
        m = MarketOrderModel(**kwargs)  # type: ignore[arg-type]
        self.session.add(m)
        await self.session.flush()
        return self._to_entity(m)

    async def update(self, order: MarketOrder) -> MarketOrder:
        stmt = (
            update(MarketOrderModel)
            .where(MarketOrderModel.id == order.id)
            .values(
                filled_quantity=order.filled_quantity,
                status=order.status.value,
            )
            .returning(MarketOrderModel)
        )
        m = (await self.session.execute(stmt)).scalar_one()
        return self._to_entity(m)

    async def record_trade(
        self, world_id: int, buy_id: int, sell_id: int, resource: str, qty: float, price: float
    ) -> None:
        self.session.add(MarketTradeModel(
            world_id=world_id, buy_order_id=buy_id, sell_order_id=sell_id,
            resource_key=resource, quantity=qty, unit_price=price, total=qty * price,
        ))

    @staticmethod
    def _to_entity(m: MarketOrderModel) -> MarketOrder:
        return MarketOrder(
            id=m.id,
            world_id=m.world_id,
            country_id=m.country_id,
            side=MarketOrderSide(m.side),
            resource_key=m.resource_key,
            quantity=m.quantity,
            unit_price=m.unit_price,
            status=MarketOrderStatus(m.status),
            filled_quantity=m.filled_quantity,
            created_at=m.created_at,
            expires_at=m.expires_at,
        )


# ----------------------------- War & Diplomacy -----------------------------

class WarRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_by_world(self, world_id: int) -> list[War]:
        stmt = select(WarModel).where(WarModel.world_id == world_id)
        rows = (await self.session.execute(stmt)).scalars().all()
        return [self._to_entity(m) for m in rows]

    async def list_active_for_country(self, country_id: int) -> list[War]:
        stmt = select(WarModel).where(
            ((WarModel.attacker_id == country_id) | (WarModel.defender_id == country_id))
            & WarModel.status.in_([WarStatus.DECLARED.value, WarStatus.ACTIVE.value])
        )
        rows = (await self.session.execute(stmt)).scalars().all()
        return [self._to_entity(m) for m in rows]

    async def create(self, **kwargs: object) -> War:
        m = WarModel(**kwargs)  # type: ignore[arg-type]
        self.session.add(m)
        await self.session.flush()
        return self._to_entity(m)

    async def update(self, war: War) -> War:
        stmt = (
            update(WarModel)
            .where(WarModel.id == war.id)
            .values(
                status=war.status.value,
                ended_at=war.ended_at,
                winner_id=war.winner_id,
                attacker_war_score=war.attacker_war_score,
                defender_war_score=war.defender_war_score,
            )
            .returning(WarModel)
        )
        m = (await self.session.execute(stmt)).scalar_one()
        return self._to_entity(m)

    async def record_battle(self, **kwargs: object) -> None:
        self.session.add(BattleModel(**kwargs))  # type: ignore[arg-type]

    @staticmethod
    def _to_entity(m: WarModel) -> War:
        return War(
            id=m.id,
            world_id=m.world_id,
            attacker_id=m.attacker_id,
            defender_id=m.defender_id,
            status=WarStatus(m.status),
            war_type=m.war_type,
            declared_at=m.declared_at,
            ended_at=m.ended_at,
            winner_id=m.winner_id,
            attacker_war_score=m.attacker_war_score,
            defender_war_score=m.defender_war_score,
        )


class DiplomacyRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, a: int, b: int) -> Diplomacy | None:
        stmt = select(DiplomacyModel).where(
            ((DiplomacyModel.country_a_id == a) & (DiplomacyModel.country_b_id == b))
            | ((DiplomacyModel.country_a_id == b) & (DiplomacyModel.country_b_id == a))
        )
        m = (await self.session.execute(stmt)).scalar_one_or_none()
        return self._to_entity(m) if m else None

    async def list_for_country(self, country_id: int) -> list[Diplomacy]:
        stmt = select(DiplomacyModel).where(
            (DiplomacyModel.country_a_id == country_id)
            | (DiplomacyModel.country_b_id == country_id)
        )
        rows = (await self.session.execute(stmt)).scalars().all()
        return [self._to_entity(m) for m in rows]

    async def upsert(self, diplo: Diplomacy) -> Diplomacy:
        existing = await self.get(diplo.country_a_id, diplo.country_b_id)
        if existing is None:
            m = DiplomacyModel(
                world_id=diplo.world_id,
                country_a_id=diplo.country_a_id,
                country_b_id=diplo.country_b_id,
                status=diplo.status.value,
            )
            self.session.add(m)
            await self.session.flush()
            return self._to_entity(m)
        stmt = (
            update(DiplomacyModel)
            .where(DiplomacyModel.id == existing.id)
            .values(status=diplo.status.value)
            .returning(DiplomacyModel)
        )
        m = (await self.session.execute(stmt)).scalar_one()
        return self._to_entity(m)

    @staticmethod
    def _to_entity(m: DiplomacyModel) -> Diplomacy:
        return Diplomacy(
            id=m.id,
            world_id=m.world_id,
            country_a_id=m.country_a_id,
            country_b_id=m.country_b_id,
            status=DiplomaticStatus(m.status),
        )


# ----------------------------- Alliances -----------------------------

class AllianceRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, alliance_id: int) -> Alliance | None:
        m = await self.session.get(AllianceModel, alliance_id)
        return self._to_entity(m) if m else None

    async def list_by_world(self, world_id: int) -> list[Alliance]:
        stmt = select(AllianceModel).where(AllianceModel.world_id == world_id)
        rows = (await self.session.execute(stmt)).scalars().all()
        return [self._to_entity(m) for m in rows]

    async def create(self, **kwargs: object) -> Alliance:
        m = AllianceModel(**kwargs)  # type: ignore[arg-type]
        self.session.add(m)
        await self.session.flush()
        return self._to_entity(m)

    async def members(self, alliance_id: int) -> list[AllianceMember]:
        stmt = select(AllianceMemberModel).where(AllianceMemberModel.alliance_id == alliance_id)
        rows = (await self.session.execute(stmt)).scalars().all()
        return [
            AllianceMember(
                alliance_id=r.alliance_id,
                country_id=r.country_id,
                role=AllianceRole(r.role),
                joined_at=r.joined_at,
            )
            for r in rows
        ]

    async def add_member(self, alliance_id: int, country_id: int, role: Any) -> None:
        self.session.add(AllianceMemberModel(
            alliance_id=alliance_id, country_id=country_id, role=role.value
        ))
        await self.session.flush()

    async def remove_member(self, alliance_id: int, country_id: int) -> None:
        stmt = select(AllianceMemberModel).where(
            AllianceMemberModel.alliance_id == alliance_id,
            AllianceMemberModel.country_id == country_id,
        )
        m = (await self.session.execute(stmt)).scalar_one_or_none()
        if m:
            await self.session.delete(m)

    @staticmethod
    def _to_entity(m: AllianceModel) -> Alliance:
        return Alliance(
            id=m.id,
            world_id=m.world_id,
            name=m.name,
            tag=m.tag,
            leader_id=m.leader_id,
            treasury=m.treasury,
            created_at=m.created_at,
        )


# ----------------------------- Missions -----------------------------

class MissionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_by_country(self, country_id: int) -> list[Mission]:
        stmt = select(MissionModel).where(MissionModel.country_id == country_id)
        rows = (await self.session.execute(stmt)).scalars().all()
        return [self._to_entity(m) for m in rows]

    async def upsert(self, mission: Mission) -> Mission:
        stmt = select(MissionModel).where(
            MissionModel.country_id == mission.country_id, MissionModel.key == mission.key
        )
        existing = (await self.session.execute(stmt)).scalar_one_or_none()
        if existing is None:
            m = MissionModel(
                world_id=mission.world_id,
                country_id=mission.country_id,
                key=mission.key,
                category=mission.category.value,
                status=mission.status.value,
                progress=mission.progress,
                expires_at=mission.expires_at,
            )
            self.session.add(m)
            await self.session.flush()
            return self._to_entity(m)
        stmt2 = (
            update(MissionModel)
            .where(MissionModel.id == existing.id)
            .values(
                status=mission.status.value,
                progress=mission.progress,
                claimed_at=mission.claimed_at,
            )
            .returning(MissionModel)
        )
        m = (await self.session.execute(stmt2)).scalar_one()
        return self._to_entity(m)

    @staticmethod
    def _to_entity(m: MissionModel) -> Mission:
        return Mission(
            id=m.id,
            world_id=m.world_id,
            country_id=m.country_id,
            key=m.key,
            category=m.category,  # type: ignore[arg-type]
            status=MissionStatus(m.status),
            progress=m.progress,
            claimed_at=m.claimed_at,
            expires_at=m.expires_at,
        )


# ----------------------------- Notifications -----------------------------

class NotificationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_by_player(self, player_id: int, limit: int = 50) -> list[Notification]:
        stmt = (
            select(NotificationModel)
            .where(NotificationModel.player_id == player_id)
            .order_by(NotificationModel.created_at.desc())
            .limit(limit)
        )
        rows = (await self.session.execute(stmt)).scalars().all()
        return [self._to_entity(m) for m in rows]

    async def create(self, **kwargs: object) -> Notification:
        m = NotificationModel(**kwargs)  # type: ignore[arg-type]
        self.session.add(m)
        await self.session.flush()
        return self._to_entity(m)

    async def mark_read(self, notification_id: int) -> bool:
        stmt = (
            update(NotificationModel)
            .where(NotificationModel.id == notification_id)
            .values(read_at=datetime.now(timezone.utc))
        )
        await self.session.execute(stmt)
        return True

    @staticmethod
    def _to_entity(m: NotificationModel) -> Notification:
        return Notification(
            id=m.id,
            player_id=m.player_id,
            level=NotificationLevel(m.level),
            title=m.title,
            body=m.body,
            data=m.data or {},
            read_at=m.read_at,
            created_at=m.created_at,
        )


# ----------------------------- Events -----------------------------

class GameEventRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_by_world(self, world_id: int, limit: int = 50) -> list[GameEvent]:
        stmt = (
            select(GameEventModel)
            .where(GameEventModel.world_id == world_id)
            .order_by(GameEventModel.triggered_at.desc())
            .limit(limit)
        )
        rows = (await self.session.execute(stmt)).scalars().all()
        return [self._to_entity(m) for m in rows]

    async def create(self, **kwargs: object) -> GameEvent:
        m = GameEventModel(**kwargs)  # type: ignore[arg-type]
        self.session.add(m)
        await self.session.flush()
        return self._to_entity(m)

    @staticmethod
    def _to_entity(m: GameEventModel) -> GameEvent:
        return GameEvent(
            id=m.id,
            world_id=m.world_id,
            key=m.key,
            category=m.category,  # type: ignore[arg-type]
            payload=m.payload or {},
            triggered_at=m.triggered_at,
        )


# ----------------------------- Orders -----------------------------

class OrderRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_pending(self, world_id: int, before: datetime) -> list[Order]:
        stmt = (
            select(OrderQueueModel)
            .where(
                OrderQueueModel.world_id == world_id,
                OrderQueueModel.executed_at.is_(None),
                (OrderQueueModel.scheduled_for.is_(None)) | (OrderQueueModel.scheduled_for <= before),
            )
        )
        rows = (await self.session.execute(stmt)).scalars().all()
        return [
            Order(
                id=r.id,
                world_id=r.world_id,
                country_id=r.country_id,
                type=OrderType(r.type),
                payload=r.payload or {},
                created_at=r.created_at,
                scheduled_for=r.scheduled_for,
            )
            for r in rows
        ]

    async def create(self, **kwargs: object) -> Order:
        m = OrderQueueModel(**kwargs)  # type: ignore[arg-type]
        self.session.add(m)
        await self.session.flush()
        return Order(
            id=m.id, world_id=m.world_id, country_id=m.country_id,
            type=OrderType(m.type), payload=m.payload or {},
            created_at=m.created_at, scheduled_for=m.scheduled_for,
        )

    async def mark_executed(self, order_id: int) -> None:
        stmt = (
            update(OrderQueueModel)
            .where(OrderQueueModel.id == order_id)
            .values(executed_at=datetime.now(timezone.utc))
        )
        await self.session.execute(stmt)
