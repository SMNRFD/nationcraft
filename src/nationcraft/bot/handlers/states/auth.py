"""Common FSM states for the bot."""
from __future__ import annotations

from aiogram.filters.state import State, StatesGroup


class AuthStates(StatesGroup):
    waiting_for_password = State()
    waiting_for_new_password = State()


class BuildStates(StatesGroup):
    choosing_building = State()
    choosing_count = State()


class TrainStates(StatesGroup):
    choosing_unit = State()
    choosing_count = State()


class ResearchStates(StatesGroup):
    choosing_tech = State()


class MarketStates(StatesGroup):
    choosing_side = State()
    choosing_resource = State()
    choosing_quantity = State()
    choosing_price = State()


class WarStates(StatesGroup):
    choosing_defender = State()
    choosing_units = State()
