"""Rankings service: aggregates country scores per world."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nationcraft.application.dto.game import RankingEntryDTO
from nationcraft.infrastructure.db.models import CountryModel, ResourceStockModel


class RankingService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def by_metric(self, world_id: int, metric: str, limit: int = 100) -> list[RankingEntryDTO]:
        if metric not in {
            "population", "treasury", "approval", "stability", "education", "healthcare",
            "military_power", "gdp", "research_points"
        }:
            metric = "population"

        if metric == "military_power":
            # Aggregate attack*count across all units.
            from nationcraft.infrastructure.db.models import UnitModel
            from nationcraft.core.config import game_data
            stmt = (
                select(
                    CountryModel.id,
                    CountryModel.name,
                ).where(CountryModel.world_id == world_id)
            )
            countries = {row[0]: row[1] for row in (await self.session.execute(stmt)).all()}
            scores: dict[int, float] = {}
            units_stmt = select(UnitModel).where(UnitModel.world_id == world_id)
            for u in (await self.session.execute(units_stmt)).scalars():
                udef = game_data.units.get(u.key)
                scores[u.country_id] = scores.get(u.country_id, 0.0) + (udef.attack if udef else 0) * u.count
            ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)[:limit]
            return [
                RankingEntryDTO(country_id=cid, country_name=countries.get(cid, "?"), score=score, rank=i + 1)
                for i, (cid, score) in enumerate(ranked)
            ]

        # Default: read directly from CountryModel columns.
        attr = metric
        stmt = select(CountryModel).where(
            CountryModel.world_id == world_id, CountryModel.deleted_at.is_(None)
        )
        rows = (await self.session.execute(stmt)).scalars().all()
        scored = sorted(rows, key=lambda c: getattr(c, attr, 0), reverse=True)[:limit]
        return [
            RankingEntryDTO(country_id=c.id, country_name=c.name,
                            score=float(getattr(c, attr, 0)), rank=i + 1)
            for i, c in enumerate(scored)
        ]
