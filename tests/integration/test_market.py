"""Integration tests for the market matching engine."""
from __future__ import annotations

import pytest

from nationcraft.application.services import MarketService
from nationcraft.domain.enums import MarketOrderSide, MarketOrderStatus
from nationcraft.infrastructure.db.models import CountryModel
from nationcraft.infrastructure.repositories import ResourceRepository


@pytest.mark.asyncio
async def test_buy_matches_existing_sell(session) -> None:
    # Two countries.
    seller = CountryModel(world_id=1, code="A", name="A", population=100, treasury=0)
    buyer = CountryModel(world_id=1, code="B", name="B", population=100, treasury=0)
    session.add_all([seller, buyer])
    await session.flush()
    resources = ResourceRepository(session)
    await resources.adjust(seller.id, "oil", 1000)
    await resources.adjust(buyer.id, "money", 100000)
    await session.commit()

    svc = MarketService(session)
    # Sell 100 oil @ 50.
    sell = await svc.place_order(
        world_id=1, country_id=seller.id, side="sell",
        resource_key="oil", quantity=100, unit_price=50,
    )
    # Buy 100 oil @ 60 (matches the cheaper sell).
    buy = await svc.place_order(
        world_id=1, country_id=buyer.id, side="buy",
        resource_key="oil", quantity=100, unit_price=60,
    )
    await session.commit()
    # Refetch orders from DB to see the final state (the in-memory
    # `sell` object wasn't refreshed when the buy order matched it).
    from sqlalchemy import select
    from nationcraft.infrastructure.db.models import MarketOrderModel
    sell_db = await session.scalar(select(MarketOrderModel).where(MarketOrderModel.id == sell.id))
    buy_db = await session.scalar(select(MarketOrderModel).where(MarketOrderModel.id == buy.id))
    assert buy_db.status == MarketOrderStatus.FILLED.value
    assert buy_db.filled_quantity == 100
    assert sell_db.status == MarketOrderStatus.FILLED.value

    # Money moved from buyer to seller (100 * 50 = 5000).
    seller_money = await resources.get_amount(seller.id, "money")
    buyer_money = await resources.get_amount(buyer.id, "money")
    assert seller_money == 5000
    assert buyer_money == 95000

    # Oil moved from seller to buyer (100).
    buyer_oil = await resources.get_amount(buyer.id, "oil")
    assert buyer_oil == 100


@pytest.mark.asyncio
async def test_cancel_refunds(session) -> None:
    seller = CountryModel(world_id=1, code="A", name="A", population=100, treasury=0)
    session.add(seller)
    await session.flush()
    resources = ResourceRepository(session)
    await resources.adjust(seller.id, "oil", 1000)

    svc = MarketService(session)
    order = await svc.place_order(
        world_id=1, country_id=seller.id, side="sell",
        resource_key="oil", quantity=100, unit_price=50,
    )
    await svc.cancel_order(seller.id, order.id)
    await session.commit()
    # Refunded 100 oil back.
    assert await resources.get_amount(seller.id, "oil") == 1000
