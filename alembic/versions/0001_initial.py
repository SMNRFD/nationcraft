"""Initial schema.

Revision ID: 0001
Revises:
Create Date: 2026-07-27 14:28:01
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "worlds",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(64), nullable=False),
        sa.Column("slug", sa.String(64), nullable=False, unique=True),
        sa.Column("status", sa.String(16), nullable=False, server_default="open"),
        sa.Column("player_capacity", sa.Integer, nullable=False, server_default="200"),
        sa.Column("player_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("tick_count", sa.BigInteger, nullable=False, server_default="0"),
        sa.Column("last_tick_at", sa.DateTime(timezone=True)),
        sa.Column("meta", sa.JSON, nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint("player_count <= player_capacity", name="ck_world_capacity"),
    )
    op.create_index("ix_worlds_status", "worlds", ["status"])
    op.create_index("ix_worlds_deleted_at", "worlds", ["deleted_at"])

    op.create_table(
        "players",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("telegram_id", sa.BigInteger, nullable=False, unique=True),
        sa.Column("username", sa.String(64)),
        sa.Column("locale", sa.String(8), nullable=False, server_default="en"),
        sa.Column("role", sa.String(16), nullable=False, server_default="player"),
        sa.Column("is_banned", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column("last_login_at", sa.DateTime(timezone=True)),
        sa.Column("password_hash", sa.String(255)),
        sa.Column("world_id", sa.BigInteger, sa.ForeignKey("worlds.id", ondelete="SET NULL")),
        sa.Column("country_id", sa.BigInteger),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_players_world_id", "players", ["world_id"])

    op.create_table(
        "sessions",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("player_id", sa.BigInteger, sa.ForeignKey("players.id", ondelete="CASCADE"), nullable=False),
        sa.Column("refresh_token_hash", sa.String(255), nullable=False),
        sa.Column("device_id", sa.String(128)),
        sa.Column("user_agent", sa.String(255)),
        sa.Column("ip_address", sa.String(64)),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_sessions_refresh_token_hash", "sessions", ["refresh_token_hash"])
    op.create_index("ix_sessions_expires_at", "sessions", ["expires_at"])

    op.create_table(
        "countries",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("world_id", sa.BigInteger, sa.ForeignKey("worlds.id", ondelete="CASCADE"), nullable=False),
        sa.Column("player_id", sa.BigInteger, sa.ForeignKey("players.id", ondelete="SET NULL")),
        sa.Column("code", sa.String(2), nullable=False),
        sa.Column("name", sa.String(64), nullable=False),
        sa.Column("flag_emoji", sa.String(16), server_default=""),
        sa.Column("government", sa.String(32), nullable=False, server_default="republic"),
        sa.Column("population", sa.BigInteger, nullable=False, server_default="1000000"),
        sa.Column("treasury", sa.Float, nullable=False, server_default="1000000.0"),
        sa.Column("debt", sa.Float, nullable=False, server_default="0.0"),
        sa.Column("approval", sa.Float, nullable=False, server_default="50.0"),
        sa.Column("stability", sa.Float, nullable=False, server_default="50.0"),
        sa.Column("corruption", sa.Float, nullable=False, server_default="10.0"),
        sa.Column("education", sa.Float, nullable=False, server_default="50.0"),
        sa.Column("healthcare", sa.Float, nullable=False, server_default="50.0"),
        sa.Column("electricity_balance", sa.Float, nullable=False, server_default="0.0"),
        sa.Column("water_balance", sa.Float, nullable=False, server_default="0.0"),
        sa.Column("housing_capacity", sa.BigInteger, nullable=False, server_default="1000000"),
        sa.Column("pollution", sa.Float, nullable=False, server_default="0.0"),
        sa.Column("research_points", sa.Float, nullable=False, server_default="0.0"),
        sa.Column("meta", sa.JSON, nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("world_id", "code", name="uq_world_country_code"),
    )
    op.create_index("ix_countries_world_id", "countries", ["world_id"])
    op.create_index("ix_countries_player_id", "countries", ["player_id"])
    op.create_index("ix_countries_deleted_at", "countries", ["deleted_at"])

    op.create_foreign_key(
        "fk_players_country_id", "players", "countries",
        ["country_id"], ["id"], ondelete="SET NULL"
    )

    op.create_table(
        "resource_stocks",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("world_id", sa.BigInteger, sa.ForeignKey("worlds.id", ondelete="CASCADE")),
        sa.Column("country_id", sa.BigInteger, sa.ForeignKey("countries.id", ondelete="CASCADE")),
        sa.Column("key", sa.String(64), nullable=False),
        sa.Column("amount", sa.Float, nullable=False, server_default="0.0"),
        sa.Column("capacity", sa.Float),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("country_id", "key", name="uq_country_resource"),
    )
    op.create_index("ix_resource_stocks_country_id", "resource_stocks", ["country_id"])
    op.create_index("ix_world_resource_key", "resource_stocks", ["world_id", "key"])

    op.create_table(
        "buildings",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("world_id", sa.BigInteger, sa.ForeignKey("worlds.id", ondelete="CASCADE")),
        sa.Column("country_id", sa.BigInteger, sa.ForeignKey("countries.id", ondelete="CASCADE")),
        sa.Column("key", sa.String(64), nullable=False),
        sa.Column("level", sa.Integer, nullable=False, server_default="1"),
        sa.Column("status", sa.String(16), nullable=False, server_default="planned"),
        sa.Column("position_x", sa.Integer, nullable=False, server_default="0"),
        sa.Column("position_y", sa.Integer, nullable=False, server_default="0"),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("completes_at", sa.DateTime(timezone=True)),
        sa.Column("produced_total", sa.Float, nullable=False, server_default="0.0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_buildings_country_id", "buildings", ["country_id"])
    op.create_index("ix_buildings_status", "buildings", ["status"])
    op.create_index("ix_buildings_completes_at", "buildings", ["completes_at"])

    op.create_table(
        "research_nodes",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("world_id", sa.BigInteger, sa.ForeignKey("worlds.id", ondelete="CASCADE")),
        sa.Column("country_id", sa.BigInteger, sa.ForeignKey("countries.id", ondelete="CASCADE")),
        sa.Column("key", sa.String(64), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="locked"),
        sa.Column("progress", sa.Float, nullable=False, server_default="0.0"),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("completes_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("country_id", "key", name="uq_country_tech"),
    )

    op.create_table(
        "units",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("world_id", sa.BigInteger, sa.ForeignKey("worlds.id", ondelete="CASCADE")),
        sa.Column("country_id", sa.BigInteger, sa.ForeignKey("countries.id", ondelete="CASCADE")),
        sa.Column("key", sa.String(64), nullable=False),
        sa.Column("count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("state", sa.String(16), nullable=False, server_default="idle"),
        sa.Column("region_id", sa.BigInteger),
        sa.Column("deployed_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("country_id", "key", name="uq_country_unit"),
    )

    op.create_table(
        "regions",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("world_id", sa.BigInteger, sa.ForeignKey("worlds.id", ondelete="CASCADE")),
        sa.Column("country_id", sa.BigInteger, sa.ForeignKey("countries.id", ondelete="SET NULL")),
        sa.Column("name", sa.String(64), nullable=False),
        sa.Column("is_capital", sa.Boolean, server_default=sa.text("false")),
        sa.Column("population", sa.BigInteger, server_default="0"),
        sa.Column("area_km2", sa.Float, server_default="0.0"),
        sa.Column("terrain", sa.String(32), server_default="plains"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    op.create_table(
        "market_orders",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("world_id", sa.BigInteger, sa.ForeignKey("worlds.id", ondelete="CASCADE")),
        sa.Column("country_id", sa.BigInteger, sa.ForeignKey("countries.id", ondelete="CASCADE")),
        sa.Column("side", sa.String(4), nullable=False),
        sa.Column("resource_key", sa.String(64), nullable=False),
        sa.Column("quantity", sa.Float, nullable=False),
        sa.Column("unit_price", sa.Float, nullable=False),
        sa.Column("filled_quantity", sa.Float, server_default="0.0"),
        sa.Column("status", sa.String(16), server_default="open"),
        sa.Column("expires_at", sa.DateTime(timezone=True)),
        sa.Column("meta", sa.JSON, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_market_matching", "market_orders",
                    ["world_id", "resource_key", "side", "status"])

    op.create_table(
        "market_trades",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("world_id", sa.BigInteger, sa.ForeignKey("worlds.id", ondelete="CASCADE")),
        sa.Column("buy_order_id", sa.BigInteger, sa.ForeignKey("market_orders.id", ondelete="CASCADE")),
        sa.Column("sell_order_id", sa.BigInteger, sa.ForeignKey("market_orders.id", ondelete="CASCADE")),
        sa.Column("resource_key", sa.String(64), nullable=False),
        sa.Column("quantity", sa.Float, nullable=False),
        sa.Column("unit_price", sa.Float, nullable=False),
        sa.Column("total", sa.Float, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    op.create_table(
        "diplomacies",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("world_id", sa.BigInteger, sa.ForeignKey("worlds.id", ondelete="CASCADE")),
        sa.Column("country_a_id", sa.BigInteger, sa.ForeignKey("countries.id", ondelete="CASCADE")),
        sa.Column("country_b_id", sa.BigInteger, sa.ForeignKey("countries.id", ondelete="CASCADE")),
        sa.Column("status", sa.String(32), server_default="neutral"),
        sa.Column("expires_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("country_a_id", "country_b_id", name="uq_diplo_pair"),
    )

    op.create_table(
        "wars",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("world_id", sa.BigInteger, sa.ForeignKey("worlds.id", ondelete="CASCADE")),
        sa.Column("attacker_id", sa.BigInteger, sa.ForeignKey("countries.id", ondelete="CASCADE")),
        sa.Column("defender_id", sa.BigInteger, sa.ForeignKey("countries.id", ondelete="CASCADE")),
        sa.Column("status", sa.String(16), server_default="declared"),
        sa.Column("war_type", sa.String(16), server_default="conventional"),
        sa.Column("declared_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("ended_at", sa.DateTime(timezone=True)),
        sa.Column("winner_id", sa.BigInteger),
        sa.Column("attacker_war_score", sa.Float, server_default="0.0"),
        sa.Column("defender_war_score", sa.Float, server_default="0.0"),
        sa.Column("meta", sa.JSON, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    op.create_table(
        "battles",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("war_id", sa.BigInteger, sa.ForeignKey("wars.id", ondelete="CASCADE")),
        sa.Column("attacker_id", sa.BigInteger, sa.ForeignKey("countries.id", ondelete="CASCADE")),
        sa.Column("defender_id", sa.BigInteger, sa.ForeignKey("countries.id", ondelete="CASCADE")),
        sa.Column("attacker_loss", sa.JSON, server_default="{}"),
        sa.Column("defender_loss", sa.JSON, server_default="{}"),
        sa.Column("winner_id", sa.BigInteger),
        sa.Column("occurred_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    op.create_table(
        "alliances",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("world_id", sa.BigInteger, sa.ForeignKey("worlds.id", ondelete="CASCADE")),
        sa.Column("name", sa.String(64), nullable=False),
        sa.Column("tag", sa.String(8), nullable=False),
        sa.Column("leader_id", sa.BigInteger, sa.ForeignKey("countries.id", ondelete="SET NULL")),
        sa.Column("treasury", sa.Float, server_default="0.0"),
        sa.Column("description", sa.Text, server_default=""),
        sa.Column("meta", sa.JSON, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    op.create_table(
        "alliance_members",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("alliance_id", sa.BigInteger, sa.ForeignKey("alliances.id", ondelete="CASCADE")),
        sa.Column("country_id", sa.BigInteger, sa.ForeignKey("countries.id", ondelete="CASCADE")),
        sa.Column("role", sa.String(16), server_default="member"),
        sa.Column("joined_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("alliance_id", "country_id", name="uq_alliance_member"),
    )

    op.create_table(
        "missions",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("world_id", sa.BigInteger, sa.ForeignKey("worlds.id", ondelete="CASCADE")),
        sa.Column("country_id", sa.BigInteger, sa.ForeignKey("countries.id", ondelete="CASCADE")),
        sa.Column("key", sa.String(64), nullable=False),
        sa.Column("category", sa.String(16), nullable=False),
        sa.Column("status", sa.String(16), server_default="active"),
        sa.Column("progress", sa.Float, server_default="0.0"),
        sa.Column("claim_data", sa.JSON, server_default="{}"),
        sa.Column("claimed_at", sa.DateTime(timezone=True)),
        sa.Column("expires_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    op.create_table(
        "notifications",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("player_id", sa.BigInteger, sa.ForeignKey("players.id", ondelete="CASCADE")),
        sa.Column("level", sa.String(16), server_default="info"),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("body", sa.Text, server_default=""),
        sa.Column("data", sa.JSON, server_default="{}"),
        sa.Column("read_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    op.create_table(
        "game_events",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("world_id", sa.BigInteger, sa.ForeignKey("worlds.id", ondelete="CASCADE")),
        sa.Column("key", sa.String(64), nullable=False),
        sa.Column("category", sa.String(16), nullable=False),
        sa.Column("payload", sa.JSON, server_default="{}"),
        sa.Column("triggered_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    op.create_table(
        "order_queue",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("world_id", sa.BigInteger, sa.ForeignKey("worlds.id", ondelete="CASCADE")),
        sa.Column("country_id", sa.BigInteger, sa.ForeignKey("countries.id", ondelete="CASCADE")),
        sa.Column("type", sa.String(16), nullable=False),
        sa.Column("payload", sa.JSON, server_default="{}"),
        sa.Column("scheduled_for", sa.DateTime(timezone=True)),
        sa.Column("executed_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    op.create_table(
        "audit_logs",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("actor_id", sa.BigInteger),
        sa.Column("action", sa.String(64), nullable=False),
        sa.Column("target_type", sa.String(64)),
        sa.Column("target_id", sa.String(64)),
        sa.Column("metadata", sa.JSON, server_default="{}"),
        sa.Column("ip_address", sa.String(64)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    op.create_table(
        "plugin_states",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("plugin_id", sa.String(64), nullable=False, unique=True),
        sa.Column("enabled", sa.Boolean, server_default=sa.text("true")),
        sa.Column("config", sa.JSON, server_default="{}"),
        sa.Column("version", sa.String(32), server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )


def downgrade() -> None:
    for table in [
        "plugin_states", "audit_logs", "order_queue", "game_events", "notifications",
        "missions", "alliance_members", "alliances", "battles", "wars", "diplomacies",
        "market_trades", "market_orders", "regions", "units", "research_nodes",
        "buildings", "resource_stocks", "countries", "sessions", "players", "worlds",
    ]:
        op.drop_table(table)
