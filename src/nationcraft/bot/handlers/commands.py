"""Command handlers: /start, /help, /login, /register, /play, /cancel."""
from __future__ import annotations

from aiogram import Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from nationcraft.bot.api_client import api_client
from nationcraft.bot.keyboards import main_menu_keyboard
from nationcraft.bot.handlers.states.auth import AuthStates
from nationcraft.core.logging import get_logger

log = get_logger(__name__)
router = Router()


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer(
        "🏰 *Welcome to NationCraft*\n\n"
        "Become the ruler of a country and lead it to greatness.\n\n"
        "Type /register to create an account, or /login if you already have one.",
        reply_markup=main_menu_keyboard(),
        parse_mode="Markdown",
    )


@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    await message.answer(
        "*Commands*\n"
        "/start — main menu\n"
        "/register — create account\n"
        "/login — sign in\n"
        "/play — open the game dashboard\n"
        "/cancel — abort current action\n"
        "/language — switch language",
        parse_mode="Markdown",
    )


@router.message(Command("register"))
async def cmd_register(message: Message, state: FSMContext) -> None:
    await state.set_state(AuthStates.waiting_for_new_password)
    await message.answer(
        "Please choose a password (min 8 chars). I will hash it with Argon2id."
    )


@router.message(AuthStates.waiting_for_new_password)
async def process_register(message: Message, state: FSMContext) -> None:
    password = (message.text or "").strip()
    if len(password) < 8:
        await message.answer("Password too short. Min 8 characters.")
        return
    user = message.from_user
    try:
        data = await api_client.register(
            telegram_id=user.id, password=password,
            username=user.username, locale=(user.language_code or "en")[:2],
        )
    except Exception as exc:  # noqa: BLE001
        await message.answer(f"❌ Registration failed: {exc}")
        return
    await state.clear()
    await message.answer(
        f"✅ Welcome, *{user.full_name}*!\nYour access token has been saved.\n\n"
        "Type /play to choose a country.",
        parse_mode="Markdown",
        reply_markup=main_menu_keyboard(),
    )


@router.message(Command("login"))
async def cmd_login(message: Message, state: FSMContext) -> None:
    await state.set_state(AuthStates.waiting_for_password)
    await message.answer("Please send your password.")


@router.message(AuthStates.waiting_for_password)
async def process_login(message: Message, state: FSMContext) -> None:
    password = (message.text or "").strip()
    user = message.from_user
    try:
        await api_client.login(telegram_id=user.id, password=password)
    except Exception as exc:  # noqa: BLE001
        await message.answer(f"❌ Login failed: {exc}")
        return
    await state.clear()
    await message.answer("✅ Logged in. Type /play to continue.", reply_markup=main_menu_keyboard())


@router.message(Command("play"))
async def cmd_play(message: Message) -> None:
    await message.answer("🌍 Main menu:", reply_markup=main_menu_keyboard())


@router.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("Action cancelled.", reply_markup=main_menu_keyboard())


@router.message(Command("language"))
async def cmd_language(message: Message) -> None:
    from nationcraft.bot.keyboards import InlineKeyboardBuilder
    from nationcraft.core.config import settings
    kb = InlineKeyboardBuilder()
    for loc in settings.supported_locales_list:
        kb.button(text=loc, callback_data=f"lang:{loc}")
    kb.adjust(2)
    await message.answer("Choose your language:", reply_markup=kb.as_markup())
