"""FastAPI application factory."""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from nationcraft.api.middleware.request_id import RequestIdMiddleware
from nationcraft.api.routers import (
    admin,
    auth,
    countries,
    market,
    military,
    production,
    social,
    worlds,
)
from nationcraft.core.config import settings
from nationcraft.core.exceptions import NationCraftError
from nationcraft.core.logging import configure_logging, get_logger

log = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging(settings.LOG_LEVEL, settings.LOG_FORMAT)
    log.info("api.startup", env=settings.ENV)

    # Verify database connectivity up-front so we surface a clear error
    # instead of letting every endpoint fail with a cryptic connection error.
    try:
        from nationcraft.infrastructure.db.session import engine
        from sqlalchemy import text
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        log.info("api.db.ok")
    except Exception as exc:  # noqa: BLE001
        log.error("api.db.unavailable", error=str(exc))
        log.error(
            "api.db.hint",
            hint="Did you start postgres? Run `docker-compose up -d` from the project root.",
        )

    # Verify Redis connectivity (optional — only warn if it fails).
    try:
        from nationcraft.infrastructure.cache import cache
        await cache._redis.ping()
        log.info("api.redis.ok")
    except Exception as exc:  # noqa: BLE001
        log.warning("api.redis.unavailable", error=str(exc))

    # Discover & load plugins.
    if settings.PLUGINS_ENABLED:
        from nationcraft.core.plugins import PluginLoader
        loader = PluginLoader(settings.plugins_dirs_list)
        loader.discover()
        loader.load_all()

    # Load game data.
    from nationcraft.core.config import game_data
    game_data.reload()

    # Load localization.
    from nationcraft.core.i18n import i18n
    i18n.load()

    yield

    log.info("api.shutdown")
    from nationcraft.infrastructure.db.session import dispose
    await dispose()


def create_app() -> FastAPI:
    app = FastAPI(
        title="NationCraft API",
        version="1.0.0",
        description="Production-quality plugin-driven Telegram nation simulation game.",
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url="/redoc",
    )
    app.add_middleware(RequestIdMiddleware)

    # ----- exception handlers -----
    @app.exception_handler(NationCraftError)
    async def _nc_error_handler(request: Request, exc: NationCraftError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "ok": False,
                "data": None,
                "error": {
                    "code": exc.code,
                    "message": str(exc),
                },
            },
        )

    @app.exception_handler(Exception)
    async def _fallback_handler(request: Request, exc: Exception) -> JSONResponse:
        log.exception("api.unhandled_error", path=request.url.path)
        return JSONResponse(
            status_code=500,
            content={
                "ok": False,
                "data": None,
                "error": {"code": "internal_error", "message": "internal server error"},
            },
        )

    # ----- routers -----
    app.include_router(auth.router)
    app.include_router(worlds.router)
    app.include_router(countries.router)
    app.include_router(production.router)
    app.include_router(military.router)
    app.include_router(market.router)
    app.include_router(social.router)
    app.include_router(admin.router)

    @app.get("/health", tags=["meta"])
    @app.get("/health/live", tags=["meta"])
    async def health() -> dict:
        """Liveness probe — process is up."""
        return {"ok": True, "status": "ok", "version": "1.0.0"}

    @app.get("/health/ready", tags=["meta"])
    async def readiness() -> dict:
        """Readiness probe — DB + Redis reachable and ready to serve."""
        checks: dict[str, str] = {}
        # DB
        try:
            from nationcraft.infrastructure.db.session import engine
            from sqlalchemy import text
            async with engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
            checks["db"] = "ok"
        except Exception as exc:  # noqa: BLE001
            checks["db"] = f"error: {exc}"
        # Redis
        try:
            from nationcraft.infrastructure.cache import cache
            await cache._redis.ping()
            checks["redis"] = "ok"
        except Exception as exc:  # noqa: BLE001
            checks["redis"] = f"error: {exc}"
        ok = all(v == "ok" for v in checks.values())
        return {"ok": ok, "status": "ok" if ok else "degraded", "checks": checks}

    return app


app = create_app()
