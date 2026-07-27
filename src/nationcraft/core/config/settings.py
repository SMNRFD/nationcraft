"""Application settings loaded from environment with pydantic-settings."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Strongly-typed application settings.

    Values are loaded from environment variables or a local ``.env`` file.
    Every magic number used by the application lives here so that no
    business logic depends on hard-coded values.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    # ---- Runtime ----
    ENV: str = "development"
    LOG_LEVEL: str = "INFO"
    LOG_FORMAT: str = "json"  # "json" or "console"
    SECRET_KEY: str = Field(default="dev-only-do-not-use-in-production")
    JWT_ISSUER: str = "nationcraft"
    JWT_ACCESS_TTL_SECONDS: int = 900
    JWT_REFRESH_TTL_SECONDS: int = 2_592_000
    ARGON2_MEMORY_KIB: int = 65_536
    ARGON2_ITERATIONS: int = 3
    ARGON2_PARALLELISM: int = 2

    # ---- Database ----
    DATABASE_URL: str = "postgresql+asyncpg://nationcraft:nationcraft@localhost:5432/nationcraft"
    DB_POOL_SIZE: int = 20
    DB_MAX_OVERFLOW: int = 20
    DB_POOL_TIMEOUT: int = 30

    # ---- Redis ----
    REDIS_URL: str = "redis://localhost:6379/0"

    # ---- API ----
    API_HOST: str = "0.0.0.0"
    API_PORT: int = 8000
    API_WORKERS: int = 4
    API_BASE_URL: str = "http://localhost:8000"

    # ---- Telegram ----
    TELEGRAM_BOT_TOKEN: str = ""
    TELEGRAM_WEBHOOK_URL: str = ""
    TELEGRAM_WEBHOOK_SECRET: str = ""
    TELEGRAM_ADMIN_IDS: str = ""
    TELEGRAM_API_BASE: str = "https://api.telegram.org"

    # ---- Game ----
    TICK_INTERVAL_SECONDS: int = 60
    WORLD_PLAYER_CAPACITY: int = 200
    WORLD_AUTO_CREATE: bool = True
    DEFAULT_LOCALE: str = "en"
    SUPPORTED_LOCALES: str = "en,fa"

    # ---- Plugins ----
    PLUGINS_ENABLED: bool = True
    PLUGINS_DIRS: str = "plugins"

    # ---- Rate limiting ----
    RATE_LIMIT_LOGIN_PER_MINUTE: int = 5
    RATE_LIMIT_API_PER_MINUTE: int = 300
    RATE_LIMIT_BOT_PER_USER_PER_MINUTE: int = 120

    # ---- Backups ----
    BACKUP_DIR: str = "/var/lib/nationcraft/backups"
    BACKUP_RETENTION_DAYS: int = 14

    @field_validator("TELEGRAM_ADMIN_IDS")
    @classmethod
    def _parse_admin_ids(cls, v: str) -> str:
        return ",".join(x.strip() for x in v.split(",") if x.strip())

    @property
    def admin_ids(self) -> set[int]:
        return {int(x) for x in self.TELEGRAM_ADMIN_IDS.split(",") if x.strip().isdigit()}

    @property
    def supported_locales_list(self) -> list[str]:
        return [x.strip() for x in self.SUPPORTED_LOCALES.split(",") if x.strip()]

    @property
    def plugins_dirs_list(self) -> list[Path]:
        return [Path(p) for p in self.PLUGINS_DIRS.split(",") if p.strip()]

    @property
    def is_production(self) -> bool:
        return self.ENV == "production"

    @property
    def is_dev(self) -> bool:
        return self.ENV == "development"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


# Module-level singleton for convenience imports.
settings: Settings = get_settings()
