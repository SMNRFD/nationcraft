"""Game data loader: persists static YAML data into DB for admin edits."""
from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession


class GameDataService:
    """Loads/refreshes the in-memory game data registry from YAML.

    The data itself stays in YAML files (single source of truth) for
    hot-reload semantics; this service exists for the admin API endpoint
    that triggers reload and reports on the loaded definitions.
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def load_all(self) -> dict:
        from nationcraft.core.config import game_data
        game_data.reload()
        return {
            "resources": len(game_data.resources),
            "buildings": len(game_data.buildings),
            "units": len(game_data.units),
            "techs": len(game_data.techs),
            "countries": len(game_data.countries),
            "events": len(game_data.events),
            "missions": len(game_data.missions),
        }
