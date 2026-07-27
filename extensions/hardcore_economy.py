"""Hardcore Economy extension.

Demonstrates how to override game calculations via hooks (without
modifying core source code). Drops resource production by 20% globally
and increases unit maintenance by 50%.
"""
from __future__ import annotations

from nationcraft.core.extensions import HookPriority, hook


@hook("production.output", priority=HookPriority.LOW)
def nerf_production(prod: dict, *, building=None, level: int = 1, delta: int = 60) -> dict:
    """Reduce all production by 20% (hardcore mode)."""
    if not prod:
        return prod
    return {k: v * 0.8 for k, v in prod.items()}


@hook("combat.resolve", priority=HookPriority.HIGH)
def deadlier_combat(default, *, attacker_units=None, defender_units=None):
    """Make combat 50% more lethal by post-processing the default result.

    The default BattleResult is computed first; we just bump loss counts.
    """
    if default is None:
        return default
    # default is a BattleResult dataclass
    new_a = {k: int(v * 1.5) for k, v in default.attacker_losses.items()}
    new_d = {k: int(v * 1.5) for k, v in default.defender_losses.items()}
    from dataclasses import replace
    return replace(default, attacker_losses=new_a, defender_losses=new_d)
