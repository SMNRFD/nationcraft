"""Catalog of well-known event types used across the system.

This file is the canonical reference — plugins/extensions are encouraged
to import these constants instead of string literals.
"""
from __future__ import annotations

# Player lifecycle
PLAYER_REGISTERED = "player.registered"
PLAYER_LOGGED_IN = "player.logged_in"
PLAYER_LOGGED_OUT = "player.logged_out"
PLAYER_BANNED = "player.banned"

# World
WORLD_CREATED = "world.created"
WORLD_FILLED = "world.filled"

# Country
COUNTRY_SELECTED = "country.selected"
COUNTRY_ABANDONED = "country.abandoned"

# Production
FACTORY_BUILT = "factory.built"
FACTORY_UPGRADED = "factory.upgraded"
PRODUCTION_TICK = "production.tick"

# Research
RESEARCH_QUEUED = "research.queued"
RESEARCH_COMPLETED = "research.completed"

# Military
UNIT_TRAINED = "unit.trained"
UNIT_DEPLOYED = "unit.deployed"

# War
WAR_DECLARED = "war.declared"
ATTACK_STARTED = "attack.started"
ATTACK_FINISHED = "attack.finished"
OCCUPATION_CHANGED = "occupation.changed"

# Market
MARKET_TRADE_LISTED = "market.listed"
MARKET_TRADE_COMPLETED = "market.completed"
MARKET_TRADE_CANCELLED = "market.cancelled"

# Population
POPULATION_UPDATED = "population.updated"
PROTEST_STARTED = "population.protest_started"

# Diplomacy
ALLIANCE_CREATED = "alliance.created"
ALLIANCE_INVITED = "alliance.invited"
DIPLOMACY_CHANGED = "diplomacy.changed"

# Tick
TICK_STARTED = "tick.started"
TICK_FINISHED = "tick.finished"

# Plugins / system
PLUGIN_LOADED = "plugin.loaded"
PLUGIN_UNLOADED = "plugin.unloaded"
EXTENSION_REGISTERED = "extension.registered"

# Missions
MISSION_COMPLETED = "mission.completed"
ACHIEVEMENT_UNLOCKED = "achievement.unlocked"

# Notifications
NOTIFICATION_QUEUED = "notification.queued"

# Events
GAME_EVENT_TRIGGERED = "event.triggered"
