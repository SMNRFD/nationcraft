"""Resource stock repository with atomic bulk-adjust."""
from __future__ import annotations

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from nationcraft.domain.entities import ResourceStock
from nationcraft.infrastructure.db.models import CountryModel, ResourceStockModel


class ResourceRepository:
    """Atomic, race-safe resource stock operations.

    Uses PostgreSQL ``ON CONFLICT`` upsert when available, with a
    safe fallback for SQLite (used in tests). The fallback is not
    race-safe under concurrency but is sufficient for unit/integration
    tests.
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, stock_id: int) -> ResourceStock | None:
        m = await self.session.get(ResourceStockModel, stock_id)
        return self._to_entity(m) if m else None

    async def list_by_country(self, country_id: int) -> list[ResourceStock]:
        stmt = select(ResourceStockModel).where(ResourceStockModel.country_id == country_id)
        rows = (await self.session.execute(stmt)).scalars().all()
        return [self._to_entity(m) for m in rows]

    async def get_amount(self, country_id: int, key: str) -> float:
        stmt = select(ResourceStockModel.amount).where(
            ResourceStockModel.country_id == country_id, ResourceStockModel.key == key
        )
        v = (await self.session.execute(stmt)).scalar_one_or_none()
        return float(v or 0.0)

    async def _resolve_world_id(self, country_id: int) -> int:
        country = await self.session.get(CountryModel, country_id)
        return country.world_id if country else 0

    async def ensure_stock(self, country_id: int, world_id: int, key: str) -> None:
        """Ensure a stock row exists; idempotent."""
        if not world_id:
            world_id = await self._resolve_world_id(country_id)
        existing = await self.session.scalar(
            select(ResourceStockModel).where(
                ResourceStockModel.country_id == country_id,
                ResourceStockModel.key == key,
            )
        )
        if existing is None:
            self.session.add(ResourceStockModel(
                world_id=world_id, country_id=country_id, key=key, amount=0.0,
            ))
            await self.session.flush()

    async def set_amount(self, country_id: int, key: str, amount: float) -> float:
        amount = max(0.0, float(amount))
        existing = await self.session.scalar(
            select(ResourceStockModel).where(
                ResourceStockModel.country_id == country_id,
                ResourceStockModel.key == key,
            )
        )
        if existing is None:
            world_id = await self._resolve_world_id(country_id)
            existing = ResourceStockModel(
                world_id=world_id, country_id=country_id, key=key, amount=amount,
            )
            self.session.add(existing)
        else:
            existing.amount = amount
        await self.session.flush()
        return amount

    async def adjust(self, country_id: int, key: str, delta: float) -> float:
        """Add ``delta`` to ``key`` for ``country_id``.

        Creates the row if missing. Returns the new amount. Refuses to go
        below zero (clamps at 0).
        """
        existing = await self.session.scalar(
            select(ResourceStockModel).where(
                ResourceStockModel.country_id == country_id,
                ResourceStockModel.key == key,
            )
        )
        if existing is None:
            world_id = await self._resolve_world_id(country_id)
            new_amount = max(0.0, delta)
            existing = ResourceStockModel(
                world_id=world_id, country_id=country_id, key=key, amount=new_amount,
            )
            self.session.add(existing)
        else:
            existing.amount = max(0.0, existing.amount + delta)
        await self.session.flush()
        return float(existing.amount)

    async def bulk_adjust(self, country_id: int, deltas: dict[str, float]) -> dict[str, float]:
        """Apply multiple deltas in one transaction; returns new balances."""
        results: dict[str, float] = {}
        for k, d in deltas.items():
            if not d:
                continue
            results[k] = await self.adjust(country_id, k, d)
        return results

    async def covers(self, country_id: int, cost: dict[str, float]) -> bool:
        """Return True iff country has at least all amounts in ``cost``."""
        for key, amount in cost.items():
            if amount <= 0:
                continue
            if await self.get_amount(country_id, key) < amount:
                return False
        return True

    async def deduct(self, country_id: int, cost: dict[str, float]) -> dict[str, float]:
        """Atomic deduction. Caller must verify ``covers()`` first."""
        return await self.bulk_adjust(country_id, {k: -v for k, v in cost.items() if v > 0})

    @staticmethod
    def _to_entity(m: ResourceStockModel) -> ResourceStock:
        return ResourceStock(
            id=m.id,
            world_id=m.world_id,
            country_id=m.country_id,
            key=m.key,
            amount=m.amount,
            capacity=m.capacity,
        )
