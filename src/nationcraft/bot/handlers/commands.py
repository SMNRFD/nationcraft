"""Command handlers: /start, /help, /login, /register, /play, /cancel, /language, /resetpassword, /panel."""
from __future__ import annotations

from aiogram import Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from nationcraft.bot.api_client import api_client
from nationcraft.bot.handlers.states.auth import AuthStates
from nationcraft.bot.keyboards import InlineKeyboardBuilder, main_menu_keyboard
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
    """Handle /register.

    If the user is already registered (has a token), show a friendly
    'already registered' message instead of asking for a new password.
    """
    user = message.from_user
    # If we already have a token for this user, they're registered.
    if api_client.get_token(user.id):
        await message.answer(
            _("auth.already_registered", locale=locale),
            reply_markup=main_menu_keyboard(),
        )
        return
    # Also check via API if the user exists (handles restarts where the
    # in-memory token was lost but the DB record persists).
    # We do this by attempting a /auth/me with no token — if it returns
    # 401 we know there's no session, but the user might still exist.
    # Simplest: just ask for a password; if register fails with
    # 'player_exists', we'll catch it in process_register.
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
        data = await api_client.register(
            telegram_id=user.id, password=password,
            username=user.username, locale=locale,
        )
    except NationCraftError as exc:
        if exc.code == "player_exists":
            # User already registered — clear state and tell them.
            await state.clear()
            await message.answer(
                _("auth.already_registered", locale=locale),
                reply_markup=main_menu_keyboard(),
            )
            return
        await message.answer(_("errors.error_with_message", locale=locale, message=str(exc)))
        return
    except Exception as exc:  # noqa: BLE001
        log.exception("bot.register.failed", error=str(exc))
        await message.answer(_("errors.internal", locale=locale))
        return
    await state.clear()
    # Send a registration success message with the player's details.
    await message.answer(
        _("auth.register_success", locale=locale, username=user.full_name),
        parse_mode="Markdown",
        reply_markup=main_menu_keyboard(),
    )
    # Send a follow-up welcome notification.
    await message.answer(
        _("auth.welcome_message", locale=locale),
        parse_mode="Markdown",
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


# -------------------- Reset Password --------------------

@router.message(Command("resetpassword"))
async def cmd_reset_password(message: Message, state: FSMContext, locale: str = "en") -> None:
    """Start the password reset flow.

    Requires the user to be logged in (have a token). Asks for the
    old password, then the new password.
    """
    user = message.from_user
    if not api_client.get_token(user.id):
        await message.answer(_("auth.must_login_first", locale=locale))
        return
    await state.set_state(AuthStates.waiting_for_old_password)
    await message.answer(_("auth.reset_password_old_prompt", locale=locale))


@router.message(AuthStates.waiting_for_old_password)
async def process_old_password(message: Message, state: FSMContext, locale: str = "en") -> None:
    """Receive the old password and ask for the new one."""
    old_password = (message.text or "").strip()
    if not old_password:
        await message.answer(_("auth.password_empty", locale=locale))
        return
    await state.update_data(old_password=old_password)
    await state.set_state(AuthStates.waiting_for_new_password_reset)
    await message.answer(_("auth.reset_password_new_prompt", locale=locale))


@router.message(AuthStates.waiting_for_new_password_reset)
async def process_new_password(message: Message, state: FSMContext, locale: str = "en") -> None:
    """Receive the new password and call the API to reset."""
    new_password = (message.text or "").strip()
    if len(new_password) < 8:
        await message.answer(_("auth.password_too_short", locale=locale))
        return
    data = await state.get_data()
    old_password = data.get("old_password", "")
    user = message.from_user
    try:
        await api_client.reset_password(
            telegram_id=user.id,
            old_password=old_password,
            new_password=new_password,
        )
    except NationCraftError as exc:
        await state.clear()
        await message.answer(
            _("errors.error_with_message", locale=locale, message=str(exc)),
            reply_markup=main_menu_keyboard(),
        )
        return
    except Exception as exc:  # noqa: BLE001
        log.exception("bot.reset_password.failed", error=str(exc))
        await state.clear()
        await message.answer(_("errors.internal", locale=locale))
        return
    await state.clear()
    # The API revoked all sessions, so clear the local token.
    api_client._tokens.pop(user.id, None)
    await message.answer(
        _("auth.password_reset_success", locale=locale),
        reply_markup=main_menu_keyboard(),
    )


# -------------------- User Panel --------------------

@router.message(Command("panel"))
async def cmd_panel(message: Message, locale: str = "en") -> None:
    """Show the user control panel: locale, reset password, profile info."""
    user = message.from_user
    token = api_client.get_token(user.id)
    if not token:
        await message.answer(_("auth.must_login_first", locale=locale))
        return

    # Fetch player profile.
    try:
        player = await api_client.get_me(user.id)
    except NationCraftError as exc:
        await message.answer(
            _("errors.error_with_message", locale=locale, message=str(exc))
        )
        return
    except Exception:  # noqa: BLE001
        await message.answer(_("errors.api_unreachable", locale=locale))
        return

    # Build panel text.
    role_label = {
        "player": _("role.player", locale=locale),
        "moderator": _("role.moderator", locale=locale),
        "admin": _("role.admin", locale=locale),
        "owner": _("role.owner", locale=locale),
    }.get(player.get("role", "player"), player.get("role", "player"))

    text = (
        f"👤 *{_('panel.title', locale=locale)}*\n\n"
        f"🆔 ID: `{player.get('id')}`\n"
        f"📱 Telegram: `{player.get('telegram_id')}`\n"
        f"👤 Username: {player.get('username') or '—'}\n"
        f"🌐 Locale: {_language_label(player.get('locale', 'en'))}\n"
        f" badge Role: {role_label}\n"
        f"🌍 World: {player.get('world_id') or '—'}\n"
        f"🏳 Country: {player.get('country_id') or '—'}\n"
    )

    kb = InlineKeyboardBuilder()
    kb.button(text=_("panel.button_language", locale=locale), callback_data="menu:settings")
    kb.button(text=_("panel.button_reset_password", locale=locale), callback_data="panel:reset_password")
    if player.get("role") in ("admin", "owner"):
        kb.button(text="🛠 Admin", callback_data="menu:admin")
    kb.adjust(1)
    kb.button(text="⬅ " + _("common.back", locale=locale), callback_data="menu:home")
    await message.answer(text, reply_markup=kb.as_markup(), parse_mode="Markdown")
