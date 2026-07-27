"""Country & region repository."""
from __future__ import annotations

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from nationcraft.domain.entities import Country, Region
from nationcraft.domain.enums import GovernmentType
from nationcraft.infrastructure.db.models import CountryModel, RegionModel


class CountryRepository:
    """SQLAlchemy implementation of :class:`ICountryRepository`."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, country_id: int) -> Country | None:
        m = await self.session.get(CountryModel, country_id)
        return self._to_entity(m) if m else None

    async def list_by_world(self, world_id: int) -> list[Country]:
        stmt = select(CountryModel).where(
            CountryModel.world_id == world_id, CountryModel.deleted_at.is_(None)
        ).order_by(CountryModel.name)
        rows = (await self.session.execute(stmt)).scalars().all()
        return [self._to_entity(m) for m in rows]

    async def list_available_in_world(self, world_id: int) -> list[Country]:
        stmt = select(CountryModel).where(
            CountryModel.world_id == world_id,
            CountryModel.player_id.is_(None),
            CountryModel.deleted_at.is_(None),
        ).order_by(CountryModel.name)
        rows = (await self.session.execute(stmt)).scalars().all()
        return [self._to_entity(m) for m in rows]

    async def create(self, **kwargs: object) -> Country:
        m = CountryModel(**kwargs)  # type: ignore[arg-type]
        self.session.add(m)
        await self.session.flush()
        return self._to_entity(m)

    async def update(self, country: Country) -> Country:
        stmt = (
            update(CountryModel)
            .where(CountryModel.id == country.id)
            .values(
                player_id=country.player_id,
                government=country.government.value,
                population=country.population,
                treasury=country.treasury,
                debt=country.debt,
                approval=country.approval,
                stability=country.stability,
                corruption=country.corruption,
                education=country.education,
                healthcare=country.healthcare,
                electricity_balance=country.electricity_balance,
                pollution=country.pollution,
            )
            .returning(CountryModel)
        )
        m = (await self.session.execute(stmt)).scalar_one()
        return self._to_entity(m)

    async def assign_player(self, country_id: int, player_id: int) -> Country:
        stmt = (
            update(CountryModel)
            .where(CountryModel.id == country_id, CountryModel.player_id.is_(None))
            .values(player_id=player_id)
            .returning(CountryModel)
        )
        m = (await self.session.execute(stmt)).scalar_one()
        return self._to_entity(m)

    @staticmethod
    def _to_entity(m: CountryModel) -> Country:
        return Country(
            id=m.id,
            world_id=m.world_id,
            player_id=m.player_id,
            code=m.code,
            name=m.name,
            flag_emoji=m.flag_emoji,
            government=GovernmentType(m.government),
            population=m.population,
            treasury=m.treasury,
            debt=m.debt,
            approval=m.approval,
            stability=m.stability,
            corruption=m.corruption,
            education=m.education,
            healthcare=m.healthcare,
            electricity_balance=m.electricity_balance,
            pollution=m.pollution,
            created_at=m.created_at,
        )


class RegionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_by_country(self, country_id: int) -> list[Region]:
        stmt = select(RegionModel).where(RegionModel.country_id == country_id)
        rows = (await self.session.execute(stmt)).scalars().all()
        return [
            Region(
                id=r.id,
                world_id=r.world_id,
                country_id=r.country_id,
                name=r.name,
                is_capital=r.is_capital,
                population=r.population,
                area_km2=r.area_km2,
                terrain=r.terrain,
            )
            for r in rows
        ]

    async def create(self, **kwargs: object) -> Region:
        m = RegionModel(**kwargs)  # type: ignore[arg-type]
        self.session.add(m)
        await self.session.flush()
        return Region(
            id=m.id, world_id=m.world_id, country_id=m.country_id, name=m.name,
            is_capital=m.is_capital, population=m.population,
            area_km2=m.area_km2, terrain=m.terrain,
        )
