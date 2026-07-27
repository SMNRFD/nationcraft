"""Wires the per-phase tick handlers to :data:`tick_engine`."""
from __future__ import annotations

from nationcraft.core.config import TickPhases
from nationcraft.core.logging import get_logger
from nationcraft.core.tick import TickContext, tick_engine
from nationcraft.infrastructure.db.session import AsyncSessionLocal

log = get_logger(__name__)


def register_default_handlers() -> None:
    """Register built-in tick handlers. Called once at app startup."""

    async def production_phase(ctx: TickContext) -> None:
        from nationcraft.application.services.production_service import ProductionService
        async with AsyncSessionLocal() as session:
            svc = ProductionService(session)
            await svc.complete_constructions()
            await svc.process_production_tick(ctx.world_id, delta_seconds=60)
            await session.commit()
            ctx.metrics["production"] = True

    async def research_phase(ctx: TickContext) -> None:
        from nationcraft.application.services.research_service import ResearchService
        async with AsyncSessionLocal() as session:
            svc = ResearchService(session)
            completed = await svc.advance_research_tick(ctx.world_id, delta_seconds=60)
            await session.commit()
            ctx.metrics["research_completed"] = completed

    async def population_phase(ctx: TickContext) -> None:
        from nationcraft.application.services.population_service import PopulationService
        async with AsyncSessionLocal() as session:
            svc = PopulationService(session)
            await svc.process_population_tick(ctx.world_id, delta_seconds=60)
            await session.commit()
            ctx.metrics["population_updated"] = True

    async def events_phase(ctx: TickContext) -> None:
        from nationcraft.application.services.event_service import GameEventService
        async with AsyncSessionLocal() as session:
            svc = GameEventService(session)
            triggered = await svc.maybe_trigger(ctx.world_id, ctx.tick)
            await session.commit()
            ctx.metrics["events_triggered"] = triggered

    async def missions_phase(ctx: TickContext) -> None:
        from nationcraft.application.services.mission_service import MissionService
        from nationcraft.infrastructure.db.models import CountryModel
        from sqlalchemy import select
        async with AsyncSessionLocal() as session:
            countries = (await session.scalars(
                select(CountryModel).where(CountryModel.world_id == ctx.world_id)
            )).all()
            svc = MissionService(session)
            total = 0
            for c in countries:
                total += await svc.evaluate(c.id)
            await session.commit()
            ctx.metrics["missions_completed"] = total

    tick_engine.register(TickPhases.PRODUCTION, "default", production_phase)
    tick_engine.register(TickPhases.RESEARCH, "default", research_phase)
    tick_engine.register(TickPhases.POPULATION, "default", population_phase)
    tick_engine.register(TickPhases.EVENTS, "default", events_phase)
    tick_engine.register(TickPhases.MISSIONS, "default", missions_phase)
    log.info("tick.handlers.registered")
