"""Market service: order matching engine."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from nationcraft.core.events import Event, event_bus
from nationcraft.core.exceptions import GameRuleError, InsufficientResourcesError, NotFoundError
from nationcraft.domain.enums import MarketOrderSide, MarketOrderStatus
from nationcraft.infrastructure.db.models import MarketOrderModel
from nationcraft.infrastructure.repositories import MarketRepository, ResourceRepository


class MarketService:
    """Order-book market with continuous matching."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = MarketRepository(session)
        self.resources = ResourceRepository(session)

    async def place_order(
        self,
        *,
        world_id: int,
        country_id: int,
        side: str,
        resource_key: str,
        quantity: float,
        unit_price: float,
        expires_in_seconds: int | None = None,
    ) -> MarketOrderModel:
        side_enum = MarketOrderSide(side)
        if quantity <= 0 or unit_price <= 0:
            raise GameRuleError("quantity and price must be positive")

        # SELL: ensure seller has the resource; lock via deduction (refund on cancellation).
        if side_enum == MarketOrderSide.SELL:
            current = await self.resources.get_amount(country_id, resource_key)
            if current < quantity:
                raise InsufficientResourcesError("insufficient resources to sell")
            await self.resources.adjust(country_id, resource_key, -quantity)
        # BUY: ensure buyer has money; lock via deduction.
        elif side_enum == MarketOrderSide.BUY:
            money = await self.resources.get_amount(country_id, "money")
            needed = quantity * unit_price
            if money < needed:
                raise InsufficientResourcesError("insufficient money")
            await self.resources.adjust(country_id, "money", -needed)

        expires_at = (
            datetime.now(timezone.utc) + timedelta(seconds=expires_in_seconds)
            if expires_in_seconds else None
        )
        order = await self.repo.create(
            world_id=world_id,
            country_id=country_id,
            side=side_enum.value,
            resource_key=resource_key,
            quantity=quantity,
            unit_price=unit_price,
            filled_quantity=0.0,
            status=MarketOrderStatus.OPEN.value,
            expires_at=expires_at,
        )
        await self._match(world_id, order)
        return order

    async def cancel_order(self, country_id: int, order_id: int) -> None:
        m = await self.session.get(MarketOrderModel, order_id)
        if m is None or m.country_id != country_id:
            raise NotFoundError("order not found")
        if m.status not in (MarketOrderStatus.OPEN.value, MarketOrderStatus.PARTIAL.value):
            raise GameRuleError("order not cancellable")

        # Refund the unfilled portion.
        remaining = m.quantity - m.filled_quantity
        if MarketOrderSide(m.side) == MarketOrderSide.SELL:
            await self.resources.adjust(country_id, m.resource_key, remaining)
        else:
            await self.resources.adjust(country_id, "money", remaining * m.unit_price)

        m.status = MarketOrderStatus.CANCELLED.value
        await self.session.flush()
        await event_bus.publish(Event(
            type="market.cancelled",
            payload={"order_id": order_id, "remaining": remaining},
        ))

    async def _match(self, world_id: int, taker: MarketOrderModel) -> None:
        """Match ``taker`` against opposing orders in price-time priority.

        Note: ``taker`` is a *domain entity* (dataclass), not the ORM
        model. All mutations go through ``repo.update()`` to persist.
        """
        taker_side = MarketOrderSide(taker.side)
        opposite_orders = await self.repo.matching_orders(
            world_id, taker_side, taker.resource_key
        )
        for maker in opposite_orders:
            if taker.filled_quantity >= taker.quantity:
                break
            # Price compatibility: BUY taker accepts prices ≤ its; SELL taker accepts ≥ its.
            if taker_side == MarketOrderSide.BUY and maker.unit_price > taker.unit_price:
                break
            if taker_side == MarketOrderSide.SELL and maker.unit_price < taker.unit_price:
                break

            fill_qty = min(
                taker.quantity - taker.filled_quantity,
                maker.quantity - maker.filled_quantity,
            )
            fill_price = maker.unit_price  # price-time priority favors resting order

            # Settle: BUY taker receives resource & pays money; SELL taker opposite.
            if taker_side == MarketOrderSide.BUY:
                await self.resources.adjust(taker.country_id, taker.resource_key, fill_qty)
                # Refund price difference vs. what was locked (taker locked at maker price).
                if fill_price < taker.unit_price:
                    refund = (taker.unit_price - fill_price) * fill_qty
                    await self.resources.adjust(taker.country_id, "money", refund)
                await self.resources.adjust(maker.country_id, "money", fill_qty * fill_price)
            else:
                await self.resources.adjust(taker.country_id, "money", fill_qty * fill_price)
                await self.resources.adjust(maker.country_id, maker.resource_key, fill_qty)

            taker.filled_quantity += fill_qty
            maker.filled_quantity += fill_qty
            maker.status = (
                MarketOrderStatus.FILLED if maker.filled_quantity >= maker.quantity
                else MarketOrderStatus.PARTIAL
            )
            # Persist maker changes.
            await self.repo.update(maker)
            await self.repo.record_trade(
                world_id=world_id,
                buy_id=taker.id if taker_side == MarketOrderSide.BUY else maker.id,
                sell_id=maker.id if taker_side == MarketOrderSide.BUY else taker.id,
                resource=taker.resource_key,
                qty=fill_qty,
                price=fill_price,
            )
            await event_bus.publish(Event(
                type="market.completed", world_id=world_id,
                payload={"resource": taker.resource_key, "qty": fill_qty, "price": fill_price},
            ))

        taker.status = (
            MarketOrderStatus.FILLED if taker.filled_quantity >= taker.quantity
            else (MarketOrderStatus.PARTIAL if taker.filled_quantity > 0
                  else MarketOrderStatus.OPEN)
        )
        # Persist taker changes.
        await self.repo.update(taker)

    async def list_open_orders(self, world_id: int) -> list[MarketOrderModel]:
        return await self.repo.list_open_orders(world_id)

    async def list_country_orders(self, country_id: int) -> list[MarketOrderModel]:
        return await self.repo.list_by_country(country_id)
