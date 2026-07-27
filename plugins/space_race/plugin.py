"""Space Race plugin.

Demonstrates the four ways a plugin can extend the game:

1. Register new static content (resource, building, technology).
2. Subscribe to events (``country.selected`` to greet new players).
3. Register a hook handler (``production.output`` to add plasma production
   from fusion reactors).
4. Register a tick-phase hook (``tick.phase.production``) for per-tick
   bonus logic.
"""
from __future__ import annotations

from typing import Any

from nationcraft.core.config import BuildingDef, ResourceDef, TechDef
from nationcraft.core.extensions import HookPriority


def register(ctx: Any) -> None:
    """Plugin entrypoint — called by the plugin loader at startup."""
    log = ctx.logger
    log.info("space_race.starting", config=ctx.config)

    # 1. Register a new resource.
    ctx.api.register_resource(ResourceDef(
        key="plasma",
        name="Plasma",
        category="material",
        icon="🔵",
        base_price=1500.0,
        description="High-energy plasma used by fusion reactors and exotic weapons.",
    ))

    # 2. Register a new building that produces plasma.
    ctx.api.register_building(BuildingDef(
        key="fusion_reactor",
        name="Fusion Reactor",
        category="power",
        description="Produces plasma and large amounts of electricity.",
        max_level=5,
        base_cost={"money": 1000000, "steel": 500, "electronics": 200, "plasma": 10},
        cost_growth=2.0,
        base_build_time=7200,
        production={"electricity": 5000, "plasma": 5},
        consumption={"water": 100},
        workers_required=200,
        requires_tech=["fusion_drive"],
    ))

    # 3. Register a new technology.
    ctx.api.register_tech(TechDef(
        key="fusion_drive",
        name="Fusion Drive",
        branch="energy",
        tier=5,
        description="Master fusion for limitless power.",
        research_cost={"money": 5000000, "research_points": 5000, "electronics": 500},
        research_time=36000,
        requires=["renewable_energy"],
        effects={"electricity_efficiency": 0.5},
        unlocks_buildings=["fusion_reactor"],
    ))

    # 4. Event subscription: log when a country is selected.
    async def on_country_selected(event):
        log.info("space_race.country_selected",
                 country_id=event.payload.get("country_id"))

    ctx.api.on_event("country.selected", on_country_selected)

    # 5. Hook: tweak production output of fusion reactors.
    def production_override(prod: dict, *, building=None, level: int = 1, delta: int = 60):
        if building is None:
            return prod
        if getattr(building, "key", None) == "fusion_reactor":
            # Bonus: high-level reactors produce extra plasma.
            bonus = level * 0.5
            new_prod = dict(prod)
            new_prod["plasma"] = new_prod.get("plasma", 0) + bonus
            return new_prod
        return prod

    ctx.api.on_hook("production.output", production_override, priority=HookPriority.HIGH)

    # 6. Tick-phase hook: grant bonus research to countries with fusion reactors.
    async def production_phase_hook(_default, ctx_tick):
        from nationcraft.infrastructure.db.session import AsyncSessionLocal
        from nationcraft.infrastructure.db.models import BuildingModel, ResourceStockModel
        from sqlalchemy import select
        bonus = float(ctx.config.get("bonus_research_per_tick", 1.0))
        async with AsyncSessionLocal() as s:
            stmt = select(BuildingModel).where(
                BuildingModel.world_id == ctx_tick.world_id,
                BuildingModel.key == "fusion_reactor",
            )
            reactors = (await s.execute(stmt)).scalars().all()
            for r in reactors:
                rs = await s.scalar(select(ResourceStockModel).where(
                    ResourceStockModel.country_id == r.country_id,
                    ResourceStockModel.key == "research_points",
                ))
                if rs is None:
                    s.add(ResourceStockModel(
                        world_id=ctx_tick.world_id,
                        country_id=r.country_id,
                        key="research_points",
                        amount=bonus,
                    ))
                else:
                    rs.amount += bonus
            await s.commit()
        log.info("space_race.tick.bonus",
                 world_id=ctx_tick.world_id, reactors=len(reactors), bonus=bonus)

    ctx.api.on_hook("tick.phase.production", production_phase_hook,
                    priority=HookPriority.LOW)

    log.info("space_race.registered")
