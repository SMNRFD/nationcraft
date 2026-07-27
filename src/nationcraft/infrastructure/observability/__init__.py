"""Observability: metrics, health checks, audit log writes."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from nationcraft.infrastructure.db.models import AuditLogModel


@dataclass(slots=True)
class HealthCheck:
    name: str
    ok: bool
    detail: str = ""
    checked_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class AuditLogger:
    """Writes audit log rows."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def log(
        self,
        *,
        action: str,
        actor_id: int | None = None,
        target_type: str | None = None,
        target_id: str | None = None,
        metadata: dict[str, Any] | None = None,
        ip_address: str | None = None,
    ) -> None:
        self.session.add(AuditLogModel(
            actor_id=actor_id, action=action, target_type=target_type,
            target_id=target_id, extra=metadata or {}, ip_address=ip_address,
        ))
        await self.session.flush()


class MetricsRegistry:
    """Tiny in-memory metrics counter for instrumentation."""

    def __init__(self) -> None:
        self._counters: dict[str, int] = {}
        self._gauges: dict[str, float] = {}

    def inc(self, name: str, value: int = 1) -> None:
        self._counters[name] = self._counters.get(name, 0) + value

    def set_gauge(self, name: str, value: float) -> None:
        self._gauges[name] = value

    def snapshot(self) -> dict[str, Any]:
        return {"counters": dict(self._counters), "gauges": dict(self._gauges)}


metrics = MetricsRegistry()
