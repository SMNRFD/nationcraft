"""Inline keyboards, paginated lists, and breadcrumb navigation."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InlineQueryResultArticle,
    InputTextMessageContent,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder


@dataclass(slots=True)
class Page:
    """Generic pagination metadata used by the renderer."""

    items: list[Any]
    page: int
    page_size: int
    total: int

    @property
    def total_pages(self) -> int:
        return max(1, (self.total + self.page_size - 1) // self.page_size)

    @property
    def has_prev(self) -> bool:
        return self.page > 0

    @property
    def has_next(self) -> bool:
        return self.page + 1 < self.total_pages


def paginate(items: list[Any], page: int, page_size: int = 8) -> Page:
    total = len(items)
    start = page * page_size
    return Page(items=items[start:start + page_size], page=page, page_size=page_size, total=total)


def main_menu_keyboard() -> InlineKeyboardMarkup:
    """Top-level navigation menu."""
    kb = InlineKeyboardBuilder()
    kb.button(text="🌍 Country", callback_data="menu:country")
    kb.button(text="🏭 Production", callback_data="menu:production")
    kb.button(text="🛡 Military", callback_data="menu:military")
    kb.button(text="📈 Market", callback_data="menu:market")
    kb.button(text="🤝 Diplomacy", callback_data="menu:diplomacy")
    kb.button(text="🧪 Research", callback_data="menu:research")
    kb.button(text="🎯 Missions", callback_data="menu:missions")
    kb.button(text="📊 Rankings", callback_data="menu:rankings")
    kb.button(text="🔔 Notifications", callback_data="menu:notifications")
    kb.button(text="⚙ Settings", callback_data="menu:settings")
    kb.adjust(2, 2, 2, 2, 2)
    return kb.as_markup()


def back_button(target: str = "menu:home", text: str = "⬅ Back") -> InlineKeyboardButton:
    return InlineKeyboardButton(text=text, callback_data=target)


def with_back(kb: InlineKeyboardBuilder, target: str = "menu:home") -> InlineKeyboardBuilder:
    kb.row(back_button(target))
    return kb


def paginated_keyboard(
    page: Page,
    *,
    item_button: Callable[[Any], tuple[str, str]],
    page_callback_prefix: str,
    back_target: str = "menu:home",
) -> InlineKeyboardMarkup:
    """Render a paginated list with prev/next + back navigation."""
    kb = InlineKeyboardBuilder()
    for item in page.items:
        label, cb = item_button(item)
        kb.button(text=label, callback_data=cb)
    kb.adjust(1)
    nav: list[InlineKeyboardButton] = []
    if page.has_prev:
        nav.append(InlineKeyboardButton(text="⬅ Prev", callback_data=f"{page_callback_prefix}:p{page.page - 1}"))
    nav.append(InlineKeyboardButton(text=f"{page.page + 1}/{page.total_pages}", callback_data="noop"))
    if page.has_next:
        nav.append(InlineKeyboardButton(text="Next ➡", callback_data=f"{page_callback_prefix}:p{page.page + 1}"))
    if nav:
        kb.row(*nav)
    kb.row(back_button(back_target))
    return kb.as_markup()


def confirm_keyboard(yes_cb: str, no_cb: str = "menu:home") -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="✅ Confirm", callback_data=yes_cb)
    kb.button(text="❌ Cancel", callback_data=no_cb)
    kb.adjust(2)
    return kb.as_markup()
