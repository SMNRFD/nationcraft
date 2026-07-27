"""Command handlers: /start, /help, /login, /register, /play, /cancel, /language."""
from __future__ import annotations

from aiogram import Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from nationcraft.bot.api_client import api_client
from nationcraft.bot.keyboards import InlineKeyboardBuilder, main_menu_keyboard
from nationcraft.bot.handlers.states.auth import AuthStates
from nationcraft.core.exceptions import NationCraftError
from nationcraft.core.i18n import _
from nationcraft.core.logging import get_logger

log = get_logger(__name__)
router = Router()


def _language_label(code: str) -> str:
    """Human-readable label for a locale code."""
    return {
        "en": "🇬🇧 English",
        "fa": "🇮🇷 فارسی",
    }.get(code, code)


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext, locale: str = "en") -> None:
    await state.clear()
    await message.answer(
        _("common.welcome", locale=locale, username=message.from_user.full_name)
        + "\n\n"
        + _("auth.register_prompt_short", locale=locale),
        reply_markup=main_menu_keyboard(),
        parse_mode="Markdown",
    )


@router.message(Command("help"))
async def cmd_help(message: Message, locale: str = "en") -> None:
    await message.answer(
        _("help.body", locale=locale),
        parse_mode="Markdown",
    )


@router.message(Command("register"))
async def cmd_register(message: Message, state: FSMContext, locale: str = "en") -> None:
    await state.set_state(AuthStates.waiting_for_new_password)
    await message.answer(_("auth.register_prompt", locale=locale))


@router.message(AuthStates.waiting_for_new_password)
async def process_register(message: Message, state: FSMContext, locale: str = "en") -> None:
    password = (message.text or "").strip()
    if len(password) < 8:
        await message.answer(_("auth.password_too_short", locale=locale))
        return
    user = message.from_user
    try:
        await api_client.register(
            telegram_id=user.id, password=password,
            username=user.username, locale=locale,
        )
    except NationCraftError as exc:
        await message.answer(_("errors.error_with_message", locale=locale, message=str(exc)))
        return
    except Exception as exc:  # noqa: BLE001
        log.exception("bot.register.failed", error=str(exc))
        await message.answer(_("errors.internal", locale=locale))
        return
    await state.clear()
    await message.answer(
        _("auth.register_success", locale=locale, username=user.full_name),
        parse_mode="Markdown",
        reply_markup=main_menu_keyboard(),
    )


@router.message(Command("login"))
async def cmd_login(message: Message, state: FSMContext, locale: str = "en") -> None:
    await state.set_state(AuthStates.waiting_for_password)
    await message.answer(_("auth.login_prompt", locale=locale))


@router.message(AuthStates.waiting_for_password)
async def process_login(message: Message, state: FSMContext, locale: str = "en") -> None:
    password = (message.text or "").strip()
    user = message.from_user
    try:
        await api_client.login(telegram_id=user.id, password=password)
    except NationCraftError as exc:
        await message.answer(_("auth.login_failed", locale=locale, message=str(exc)))
        return
    except Exception as exc:  # noqa: BLE001
        log.exception("bot.login.failed", error=str(exc))
        await message.answer(_("errors.internal", locale=locale))
        return
    await state.clear()
    await message.answer(
        _("auth.login_success", locale=locale),
        reply_markup=main_menu_keyboard(),
    )


@router.message(Command("play"))
async def cmd_play(message: Message, locale: str = "en") -> None:
    await message.answer(
        _("menu.home", locale=locale),
        reply_markup=main_menu_keyboard(),
    )


@router.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext, locale: str = "en") -> None:
    await state.clear()
    await message.answer(
        _("common.cancel", locale=locale),
        reply_markup=main_menu_keyboard(),
    )


@router.message(Command("language"))
async def cmd_language(message: Message, locale: str = "en") -> None:
    """Show a language picker. Selection is handled by ``cb_language``."""
    from nationcraft.core.config import settings
    kb = InlineKeyboardBuilder()
    for loc in settings.supported_locales_list:
        # Mark the current locale with ✓
        label = f"✓ {_language_label(loc)}" if loc == locale else _language_label(loc)
        kb.button(text=label, callback_data=f"lang:{loc}")
    kb.adjust(2)
    await message.answer(
        _("language.choose", locale=locale),
        reply_markup=kb.as_markup(),
    )
