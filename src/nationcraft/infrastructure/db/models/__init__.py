"""SQLAlchemy ORM models — the persistence layer's concrete implementation.

All tables use ``BigInt`` primary keys, ``UUID`` for public-facing IDs
where useful, soft-delete columns, audit timestamps, and JSON columns
for free-form metadata so plugins can extend rows without migrations.

The JSON column type is portable: PostgreSQL uses native ``JSONB``,
other dialects (e.g. SQLite for tests) fall back to generic ``JSON``.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy import JSON
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.types import TypeDecorator


class PortableJSON(TypeDecorator):
    """JSON column type that uses JSONB on PostgreSQL and JSON elsewhere."""

    impl = JSON
    cache_ok = True

    def load_dialect_impl(self, dialect):  # type: ignore[no-untyped-def]
        if dialect.name == "postgresql":
            return dialect.type_descriptor(JSONB())
        return dialect.type_descriptor(JSON())


# BigInteger primary key that autoincrements on both PostgreSQL and SQLite.
# SQLite requires INTEGER PRIMARY KEY (not BIGINT) for AUTOINCREMENT semantics.
PKBigInt = BigInteger().with_variant(Integer, "sqlite")


class Base(DeclarativeBase):
    """Base class for all ORM models."""

    type_annotation_map = {dict[str, Any]: PortableJSON()}


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class SoftDeleteMixin:
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None, index=True)


# ---------- Worlds ----------

class WorldModel(Base, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "worlds"
    __table_args__ = (CheckConstraint("player_count <= player_capacity", name="ck_world_capacity"),)

    id: Mapped[int] = mapped_column(PKBigInt, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    slug: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(16), default="open", nullable=False, index=True)
    player_capacity: Mapped[int] = mapped_column(Integer, default=200, nullable=False)
    player_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    tick_count: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    last_tick_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    meta: Mapped[dict[str, Any]] = mapped_column(default=dict, server_default="{}")

    countries: Mapped[list["CountryModel"]] = relationship(back_populates="world")


# ---------- Players ----------

class PlayerModel(Base, TimestampMixin):
    __tablename__ = "players"

    id: Mapped[int] = mapped_column(PKBigInt, primary_key=True, autoincrement=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True, nullable=False)
    username: Mapped[str | None] = mapped_column(String(64))
    locale: Mapped[str] = mapped_column(String(8), default="en", nullable=False)
    role: Mapped[str] = mapped_column(String(16), default="player", nullable=False)
    is_banned: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    password_hash: Mapped[str | None] = mapped_column(String(255))
    world_id: Mapped[int | None] = mapped_column(ForeignKey("worlds.id", ondelete="SET NULL"))
    country_id: Mapped[int | None] = mapped_column(ForeignKey("countries.id", ondelete="SET NULL"))


class SessionModel(Base, TimestampMixin):
    __tablename__ = "sessions"

    id: Mapped[int] = mapped_column(PKBigInt, primary_key=True, autoincrement=True)
    player_id: Mapped[int] = mapped_column(ForeignKey("players.id", ondelete="CASCADE"), nullable=False)
    refresh_token_hash: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    device_id: Mapped[str | None] = mapped_column(String(128))
    user_agent: Mapped[str | None] = mapped_column(String(255))
    ip_address: Mapped[str | None] = mapped_column(String(64))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


# ---------- Countries ----------

class CountryModel(Base, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "countries"

    id: Mapped[int] = mapped_column(PKBigInt, primary_key=True, autoincrement=True)
    world_id: Mapped[int] = mapped_column(ForeignKey("worlds.id", ondelete="CASCADE"), nullable=False, index=True)
    player_id: Mapped[int | None] = mapped_column(ForeignKey("players.id", ondelete="SET NULL"), index=True)
    code: Mapped[str] = mapped_column(String(2), nullable=False)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    flag_emoji: Mapped[str] = mapped_column(String(16), default="")
    government: Mapped[str] = mapped_column(String(32), default="republic", nullable=False)
    population: Mapped[int] = mapped_column(BigInteger, default=1_000_000, nullable=False)
    treasury: Mapped[float] = mapped_column(Float, default=1_000_000.0, nullable=False)
    debt: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    approval: Mapped[float] = mapped_column(Float, default=50.0, nullable=False)
    stability: Mapped[float] = mapped_column(Float, default=50.0, nullable=False)
    corruption: Mapped[float] = mapped_column(Float, default=10.0, nullable=False)
    education: Mapped[float] = mapped_column(Float, default=50.0, nullable=False)
    healthcare: Mapped[float] = mapped_column(Float, default=50.0, nullable=False)
    electricity_balance: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    water_balance: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    housing_capacity: Mapped[int] = mapped_column(BigInteger, default=1_000_000, nullable=False)
    pollution: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    research_points: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    meta: Mapped[dict[str, Any]] = mapped_column(default=dict, server_default="{}")

    world: Mapped[WorldModel] = relationship(back_populates="countries")
    resources: Mapped[list["ResourceStockModel"]] = relationship(
        back_populates="country", cascade="all, delete-orphan"
    )
    buildings: Mapped[list["BuildingModel"]] = relationship(
        back_populates="country", cascade="all, delete-orphan"
    )
    units: Mapped[list["UnitModel"]] = relationship(
        back_populates="country", cascade="all, delete-orphan"
    )

    __table_args__ = (UniqueConstraint("world_id", "code", name="uq_world_country_code"),)


class ResourceStockModel(Base, TimestampMixin):
    __tablename__ = "resource_stocks"

    id: Mapped[int] = mapped_column(PKBigInt, primary_key=True, autoincrement=True)
    world_id: Mapped[int] = mapped_column(ForeignKey("worlds.id", ondelete="CASCADE"), index=True)
    country_id: Mapped[int] = mapped_column(ForeignKey("countries.id", ondelete="CASCADE"), index=True)
    key: Mapped[str] = mapped_column(String(64), nullable=False)
    amount: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    capacity: Mapped[float | None] = mapped_column(Float)

    country: Mapped[CountryModel] = relationship(back_populates="resources")

    __table_args__ = (
        UniqueConstraint("country_id", "key", name="uq_country_resource"),
        Index("ix_world_resource_key", "world_id", "key"),
    )


class BuildingModel(Base, TimestampMixin):
    __tablename__ = "buildings"

    id: Mapped[int] = mapped_column(PKBigInt, primary_key=True, autoincrement=True)
    world_id: Mapped[int] = mapped_column(ForeignKey("worlds.id", ondelete="CASCADE"), index=True)
    country_id: Mapped[int] = mapped_column(ForeignKey("countries.id", ondelete="CASCADE"), index=True)
    key: Mapped[str] = mapped_column(String(64), nullable=False)
    level: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="planned", nullable=False, index=True)
    position_x: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    position_y: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completes_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    produced_total: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)

    country: Mapped[CountryModel] = relationship(back_populates="buildings")


class ResearchNodeModel(Base, TimestampMixin):
    __tablename__ = "research_nodes"

    id: Mapped[int] = mapped_column(PKBigInt, primary_key=True, autoincrement=True)
    world_id: Mapped[int] = mapped_column(ForeignKey("worlds.id", ondelete="CASCADE"), index=True)
    country_id: Mapped[int] = mapped_column(ForeignKey("countries.id", ondelete="CASCADE"), index=True)
    key: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="locked", nullable=False, index=True)
    progress: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completes_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)

    __table_args__ = (UniqueConstraint("country_id", "key", name="uq_country_tech"),)


class UnitModel(Base, TimestampMixin):
    __tablename__ = "units"

    id: Mapped[int] = mapped_column(PKBigInt, primary_key=True, autoincrement=True)
    world_id: Mapped[int] = mapped_column(ForeignKey("worlds.id", ondelete="CASCADE"), index=True)
    country_id: Mapped[int] = mapped_column(ForeignKey("countries.id", ondelete="CASCADE"), index=True)
    key: Mapped[str] = mapped_column(String(64), nullable=False)
    count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    state: Mapped[str] = mapped_column(String(16), default="idle", nullable=False)
    region_id: Mapped[int | None] = mapped_column(BigInteger)
    deployed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    country: Mapped[CountryModel] = relationship(back_populates="units")
    __table_args__ = (UniqueConstraint("country_id", "key", name="uq_country_unit"),)


class RegionModel(Base, TimestampMixin):
    __tablename__ = "regions"

    id: Mapped[int] = mapped_column(PKBigInt, primary_key=True, autoincrement=True)
    world_id: Mapped[int] = mapped_column(ForeignKey("worlds.id", ondelete="CASCADE"), index=True)
    country_id: Mapped[int | None] = mapped_column(ForeignKey("countries.id", ondelete="SET NULL"), index=True)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    is_capital: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    population: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    area_km2: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    terrain: Mapped[str] = mapped_column(String(32), default="plains", nullable=False)


# ---------- Market ----------

class MarketOrderModel(Base, TimestampMixin):
    __tablename__ = "market_orders"

    id: Mapped[int] = mapped_column(PKBigInt, primary_key=True, autoincrement=True)
    world_id: Mapped[int] = mapped_column(ForeignKey("worlds.id", ondelete="CASCADE"), index=True)
    country_id: Mapped[int] = mapped_column(ForeignKey("countries.id", ondelete="CASCADE"), index=True)
    side: Mapped[str] = mapped_column(String(4), nullable=False)
    resource_key: Mapped[str] = mapped_column(String(64), nullable=False)
    quantity: Mapped[float] = mapped_column(Float, nullable=False)
    unit_price: Mapped[float] = mapped_column(Float, nullable=False)
    filled_quantity: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="open", nullable=False, index=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    meta: Mapped[dict[str, Any]] = mapped_column(default=dict, server_default="{}")

    __table_args__ = (
        Index("ix_market_matching", "world_id", "resource_key", "side", "status"),
    )


class MarketTradeModel(Base, TimestampMixin):
    __tablename__ = "market_trades"

    id: Mapped[int] = mapped_column(PKBigInt, primary_key=True, autoincrement=True)
    world_id: Mapped[int] = mapped_column(ForeignKey("worlds.id", ondelete="CASCADE"), index=True)
    buy_order_id: Mapped[int] = mapped_column(ForeignKey("market_orders.id", ondelete="CASCADE"))
    sell_order_id: Mapped[int] = mapped_column(ForeignKey("market_orders.id", ondelete="CASCADE"))
    resource_key: Mapped[str] = mapped_column(String(64), nullable=False)
    quantity: Mapped[float] = mapped_column(Float, nullable=False)
    unit_price: Mapped[float] = mapped_column(Float, nullable=False)
    total: Mapped[float] = mapped_column(Float, nullable=False)


# ---------- Diplomacy & War ----------

class DiplomacyModel(Base, TimestampMixin):
    __tablename__ = "diplomacies"

    id: Mapped[int] = mapped_column(PKBigInt, primary_key=True, autoincrement=True)
    world_id: Mapped[int] = mapped_column(ForeignKey("worlds.id", ondelete="CASCADE"), index=True)
    country_a_id: Mapped[int] = mapped_column(ForeignKey("countries.id", ondelete="CASCADE"))
    country_b_id: Mapped[int] = mapped_column(ForeignKey("countries.id", ondelete="CASCADE"))
    status: Mapped[str] = mapped_column(String(32), default="neutral", nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        UniqueConstraint("country_a_id", "country_b_id", name="uq_diplo_pair"),
    )


class WarModel(Base, TimestampMixin):
    __tablename__ = "wars"

    id: Mapped[int] = mapped_column(PKBigInt, primary_key=True, autoincrement=True)
    world_id: Mapped[int] = mapped_column(ForeignKey("worlds.id", ondelete="CASCADE"), index=True)
    attacker_id: Mapped[int] = mapped_column(ForeignKey("countries.id", ondelete="CASCADE"))
    defender_id: Mapped[int] = mapped_column(ForeignKey("countries.id", ondelete="CASCADE"))
    status: Mapped[str] = mapped_column(String(16), default="declared", nullable=False, index=True)
    war_type: Mapped[str] = mapped_column(String(16), default="conventional", nullable=False)
    declared_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    winner_id: Mapped[int | None] = mapped_column(BigInteger)
    attacker_war_score: Mapped[float] = mapped_column(Float, default=0.0)
    defender_war_score: Mapped[float] = mapped_column(Float, default=0.0)
    meta: Mapped[dict[str, Any]] = mapped_column(default=dict, server_default="{}")


class BattleModel(Base, TimestampMixin):
    __tablename__ = "battles"

    id: Mapped[int] = mapped_column(PKBigInt, primary_key=True, autoincrement=True)
    war_id: Mapped[int] = mapped_column(ForeignKey("wars.id", ondelete="CASCADE"), index=True)
    attacker_id: Mapped[int] = mapped_column(ForeignKey("countries.id", ondelete="CASCADE"))
    defender_id: Mapped[int] = mapped_column(ForeignKey("countries.id", ondelete="CASCADE"))
    attacker_loss: Mapped[dict[str, Any]] = mapped_column(default=dict, server_default="{}")
    defender_loss: Mapped[dict[str, Any]] = mapped_column(default=dict, server_default="{}")
    winner_id: Mapped[int | None] = mapped_column(BigInteger)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


# ---------- Alliances ----------

class AllianceModel(Base, TimestampMixin):
    __tablename__ = "alliances"

    id: Mapped[int] = mapped_column(PKBigInt, primary_key=True, autoincrement=True)
    world_id: Mapped[int] = mapped_column(ForeignKey("worlds.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    tag: Mapped[str] = mapped_column(String(8), nullable=False)
    leader_id: Mapped[int] = mapped_column(ForeignKey("countries.id", ondelete="SET NULL"))
    treasury: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    description: Mapped[str] = mapped_column(Text, default="")
    meta: Mapped[dict[str, Any]] = mapped_column(default=dict, server_default="{}")


class AllianceMemberModel(Base, TimestampMixin):
    __tablename__ = "alliance_members"

    id: Mapped[int] = mapped_column(PKBigInt, primary_key=True, autoincrement=True)
    alliance_id: Mapped[int] = mapped_column(ForeignKey("alliances.id", ondelete="CASCADE"), index=True)
    country_id: Mapped[int] = mapped_column(ForeignKey("countries.id", ondelete="CASCADE"))
    role: Mapped[str] = mapped_column(String(16), default="member", nullable=False)
    joined_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (UniqueConstraint("alliance_id", "country_id", name="uq_alliance_member"),)


# ---------- Missions ----------

class MissionModel(Base, TimestampMixin):
    __tablename__ = "missions"

    id: Mapped[int] = mapped_column(PKBigInt, primary_key=True, autoincrement=True)
    world_id: Mapped[int] = mapped_column(ForeignKey("worlds.id", ondelete="CASCADE"), index=True)
    country_id: Mapped[int] = mapped_column(ForeignKey("countries.id", ondelete="CASCADE"), index=True)
    key: Mapped[str] = mapped_column(String(64), nullable=False)
    category: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="active", nullable=False, index=True)
    progress: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    claim_data: Mapped[dict[str, Any]] = mapped_column(default=dict, server_default="{}")
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)


# ---------- Notifications ----------

class NotificationModel(Base, TimestampMixin):
    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(PKBigInt, primary_key=True, autoincrement=True)
    player_id: Mapped[int] = mapped_column(ForeignKey("players.id", ondelete="CASCADE"), index=True)
    level: Mapped[str] = mapped_column(String(16), default="info", nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    body: Mapped[str] = mapped_column(Text, default="", nullable=False)
    data: Mapped[dict[str, Any]] = mapped_column(default=dict, server_default="{}")
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


# ---------- Game Events ----------

class GameEventModel(Base, TimestampMixin):
    __tablename__ = "game_events"

    id: Mapped[int] = mapped_column(PKBigInt, primary_key=True, autoincrement=True)
    world_id: Mapped[int] = mapped_column(ForeignKey("worlds.id", ondelete="CASCADE"), index=True)
    key: Mapped[str] = mapped_column(String(64), nullable=False)
    category: Mapped[str] = mapped_column(String(16), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(default=dict, server_default="{}")
    triggered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


# ---------- Orders Queue ----------

class OrderQueueModel(Base, TimestampMixin):
    __tablename__ = "order_queue"

    id: Mapped[int] = mapped_column(PKBigInt, primary_key=True, autoincrement=True)
    world_id: Mapped[int] = mapped_column(ForeignKey("worlds.id", ondelete="CASCADE"), index=True)
    country_id: Mapped[int] = mapped_column(ForeignKey("countries.id", ondelete="CASCADE"), index=True)
    type: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    payload: Mapped[dict[str, Any]] = mapped_column(default=dict, server_default="{}")
    scheduled_for: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    executed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


# ---------- Audit Log ----------

class AuditLogModel(Base, TimestampMixin):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(PKBigInt, primary_key=True, autoincrement=True)
    actor_id: Mapped[int | None] = mapped_column(BigInteger, index=True)
    action: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    target_type: Mapped[str | None] = mapped_column(String(64))
    target_id: Mapped[str | None] = mapped_column(String(64))
    extra: Mapped[dict[str, Any]] = mapped_column(default=dict, server_default="{}")
    ip_address: Mapped[str | None] = mapped_column(String(64))


# ---------- Plugin state ----------

class PluginStateModel(Base, TimestampMixin):
    __tablename__ = "plugin_states"

    id: Mapped[int] = mapped_column(PKBigInt, primary_key=True, autoincrement=True)
    plugin_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    config: Mapped[dict[str, Any]] = mapped_column(default=dict, server_default="{}")
    version: Mapped[str] = mapped_column(String(32), default="")
