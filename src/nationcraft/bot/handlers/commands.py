"""Command handlers: /start, /help, /login, /register, /play, /cancel, /language, /resetpassword, /panel, /status, /logout.

IMPORTANT: All command handlers are registered BEFORE state handlers.
This ensures that commands like /login, /cancel, /panel work even when
the user is stuck in an FSM state (e.g. waiting_for_password).

State handlers use a ``F.text`` filter that excludes commands (text
starting with ``/``) so they only catch plain text messages.
"""
from __future__ import annotations

import httpx
from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from nationcraft.bot.api_client import api_client
from nationcraft.bot.handlers.states.auth import AuthStates
from nationcraft.bot.keyboards import InlineKeyboardBuilder, main_menu_keyboard
from nationcraft.bot.utils import escape_md, safe_send
from nationcraft.core.config import settings
from nationcraft.core.exceptions import NationCraftError, is_transient_error
from nationcraft.core.i18n import _
from nationcraft.core.logging import get_logger

log = get_logger(__name__)
router = Router()


def _language_label(code: str) -> str:
    return {"en": "🇬🇧 English", "fa": "🇮🇷 فارسی"}.get(code, code)


# Filter: message is plain text (not a command). Used to exclude
# commands from FSM state handlers so /cancel, /login, etc. always work
# even when the user is in a state like waiting_for_password.
_NOT_COMMAND = F.text & ~F.text.startswith("/")


# ====================================================================
# COMMAND HANDLERS — registered FIRST so they take priority over states
# ====================================================================

@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext, locale: str = "en") -> None:
    await state.clear()
    # Escape the username so Telegram's Markdown parser doesn't choke
    # on underscores, asterisks, etc. in the user's display name.
    # (Previously: TelegramBadRequest: can't parse entities at byte offset N)
    safe_name = escape_md(message.from_user.full_name)
    await safe_send(
        message,
        _("common.welcome", locale=locale, username=safe_name)
        + "\n\n"
        + _("auth.register_prompt_short", locale=locale),
        reply_markup=main_menu_keyboard(),
        parse_mode="Markdown",
    )


@router.message(Command("help"))
async def cmd_help(message: Message, state: FSMContext, locale: str = "en") -> None:
    await state.clear()
    await message.answer(_("help.body", locale=locale), parse_mode="Markdown")


@router.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext, locale: str = "en") -> None:
    await state.clear()
    await message.answer(
        _("common.cancel", locale=locale),
        reply_markup=main_menu_keyboard(),
    )


@router.message(Command("play"))
async def cmd_play(message: Message, state: FSMContext, locale: str = "en") -> None:
    await state.clear()
    await message.answer(
        _("menu.home", locale=locale),
        reply_markup=main_menu_keyboard(),
    )


@router.message(Command("register"))
async def cmd_register(message: Message, state: FSMContext, locale: str = "en") -> None:
    """Handle /register.

    If the user is already registered (has a token), show a friendly
    'already registered' message instead of asking for a new password.
    """
    await state.clear()
    user = message.from_user
    # If we already have a token for this user, they're registered.
    # NOTE: we don't reach into the API to verify the token here — that
    # would block the handler chain on a slow API. The token will be
    # validated on the next authenticated call (and transparently
    # refreshed if needed).
    if api_client.get_token(user.id):
        await message.answer(
            _("auth.already_registered", locale=locale),
            reply_markup=main_menu_keyboard(),
        )
        return
    await state.set_state(AuthStates.waiting_for_new_password)
    await message.answer(_("auth.register_prompt", locale=locale))


@router.message(Command("login"))
async def cmd_login(message: Message, state: FSMContext, locale: str = "en") -> None:
    """Start the login flow.

    Evicts any stale local token BEFORE entering the FSM state. This
    prevents the locale middleware from attempting to call /auth/me with
    a dead token (which previously caused a 15s hang on the next message
    when the API was slow to reject the token).
    """
    await state.clear()
    user = message.from_user
    # Drop any existing token — the user explicitly asked to log in again.
    api_client.clear_token(user.id)
    await state.set_state(AuthStates.waiting_for_password)
    await message.answer(_("auth.login_prompt", locale=locale))


@router.message(Command("logout"))
async def cmd_logout(message: Message, state: FSMContext, locale: str = "en") -> None:
    """Log the user out — revoke the server-side session and clear local tokens."""
    await state.clear()
    user = message.from_user
    if not api_client.get_token(user.id):
        await message.answer(_("auth.must_login_first", locale=locale))
        return
    # Best-effort server-side revoke; clear local state regardless.
    try:
        await api_client.logout(user.id)
    except Exception as exc:  # noqa: BLE001
        log.debug("bot.logout.api_failed", error=str(exc)[:100])
    api_client.clear_token(user.id)
    await message.answer(
        _("common.cancel", locale=locale),
        reply_markup=main_menu_keyboard(),
    )


@router.message(Command("status"))
async def cmd_status(message: Message, state: FSMContext, locale: str = "en") -> None:
    """Show diagnostic info: FSM state, token presence, API connectivity.

    Useful for users to debug issues like 'I can't log in' or 'the bot
    says I'm not authenticated but I registered'.
    """
    await state.clear()
    user = message.from_user
    current_state = await state.get_state()
    has_access = api_client.get_token(user.id) is not None
    has_refresh = api_client.get_refresh_token(user.id) is not None
    is_admin = user.id in settings.admin_ids if hasattr(settings, 'admin_ids') else False

    # Test API connectivity — try both /health and /health/ready
    api_status = "unknown"
    api_latency_ms = None
    api_detail = ""
    try:
        import time as _time
        start = _time.perf_counter()
        async with httpx.AsyncClient(timeout=10.0) as _c:
            r = await _c.get(f"{api_client.base_url}/health")
            elapsed = (_time.perf_counter() - start) * 1000
            if r.status_code == 200:
                api_status = "ok"
                api_latency_ms = round(elapsed)
                # Also check /health/ready for DB status
                try:
                    r2 = await _c.get(f"{api_client.base_url}/health/ready", timeout=3.0)
                    if r2.status_code == 200:
                        ready = r2.json()
                        checks = ready.get("checks", {})
                        db_status = checks.get("db", "unknown")
                        api_detail = f"\n   DB: {db_status}"
                        if ready.get("status") == "degraded":
                            api_detail += " ⚠️ degraded"
                except Exception:
                    pass
            else:
                api_status = f"http_{r.status_code}"
                api_detail = f"\n   Response: {r.text[:100]}"
    except httpx.ConnectError as e:
        api_status = "unreachable"
        api_detail = f"\n   Connection refused. Is the API running?"
        api_detail += f"\n   Error: {type(e).__name__}: {str(e)[:100]}"
    except httpx.TimeoutException:
        api_status = "timeout"
        api_detail = f"\n   API did not respond within 10 seconds."
    except Exception as e:
        api_status = f"error: {type(e).__name__}"
        api_detail = f"\n   {str(e)[:150]}"

    # Check if DATABASE_URL looks valid
    db_url = settings.DATABASE_URL or "(not set)"
    db_ok = bool(db_url) and "://" in db_url

    text = (
        f"🔍 *Bot status*\n\n"
        f"👤 Telegram ID: `{user.id}`\n"
        f"🎭 Admin: {is_admin}\n"
        f"🔖 FSM state: `{current_state or 'none'}`\n"
        f"🔑 Access token: {'✅ present' if has_access else '❌ missing'}\n"
        f"🔄 Refresh token: {'✅ present' if has_refresh else '❌ missing'}\n"
        f"🌐 API URL: `{api_client.base_url}`\n"
        f"📡 API status: {api_status}"
        + (f" ({api_latency_ms}ms)" if api_latency_ms is not None else "")
        + api_detail
        + "\n"
        f"🗄 DB URL: `{db_url[:60]}{'...' if len(db_url) > 60 else ''}`\n"
        f"🌍 Locale: {_language_label(locale)}\n"
    )

    if api_status != "ok":
        text += (
            f"\n⚠️ *Diagnosis:*\n"
            f"The API is not reachable. Make sure you started the game with:\n"
            f"  `python main.py --local`\n"
            f"(NOT `--only bot` — that skips the API server.)\n"
            f"Also run `python main.py --local --initdb` first to create the database."
        )
    await safe_send(message, text, parse_mode="Markdown", reply_markup=main_menu_keyboard())


@router.message(Command("language"))
async def cmd_language(message: Message, state: FSMContext, locale: str = "en") -> None:
    await state.clear()
    kb = InlineKeyboardBuilder()
    for loc in settings.supported_locales_list:
        label = f"✓ {_language_label(loc)}" if loc == locale else _language_label(loc)
        kb.button(text=label, callback_data=f"lang:{loc}")
    kb.adjust(2)
    await message.answer(
        _("language.choose", locale=locale),
        reply_markup=kb.as_markup(),
    )


@router.message(Command("resetpassword"))
async def cmd_reset_password(message: Message, state: FSMContext, locale: str = "en") -> None:
    """Start the password reset flow."""
    await state.clear()
    user = message.from_user
    if not api_client.get_token(user.id):
        await message.answer(_("auth.must_login_first", locale=locale))
        return
    await state.set_state(AuthStates.waiting_for_old_password)
    await message.answer(_("auth.reset_password_old_prompt", locale=locale))


@router.message(Command("panel"))
async def cmd_panel(message: Message, state: FSMContext, locale: str = "en") -> None:
    """Show the user control panel."""
    await state.clear()
    user = message.from_user
    token = api_client.get_token(user.id)
    if not token:
        await message.answer(_("auth.must_login_first", locale=locale))
        return

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

    # ``get_me`` returns None on auth OR network errors. We must
    # distinguish:
    # - If the token is still in api_client._tokens, get_me returned
    #   None due to a network error — DON'T clear the token, just tell
    #   the user the API is unreachable.
    # - If the token is gone (evicted by _request on 401 after refresh
    #   failed), it was an auth error — tell the user to log in again.
    if not player:
        if api_client.get_token(user.id) is None:
            # Auth failed (token was evicted). Tell user to log in.
            await message.answer(_("auth.must_login_first", locale=locale))
            return
        # Network error — token is still valid. Don't log the user out.
        await message.answer(_("errors.api_unreachable", locale=locale))
        return

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
        f"🎖 Role: {role_label}\n"
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


# ====================================================================
# STATE HANDLERS — registered AFTER commands, with ~Command() filter
# so they only catch plain text, never commands.
# ====================================================================

@router.message(AuthStates.waiting_for_new_password, _NOT_COMMAND)
async def process_register(message: Message, state: FSMContext, locale: str = "en") -> None:
    """Handle password input during registration."""
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
            # Definitive auth error — clear state, user must /login.
            await state.clear()
            await message.answer(
                _("auth.already_registered", locale=locale),
                reply_markup=main_menu_keyboard(),
            )
            return
        if is_transient_error(exc):
            # Network error (502, 503, timeout) — DON'T clear state
            # so the user can retry by sending the password again.
            # Include the actual error so the user can diagnose.
            await message.answer(
                f"⚠️ Cannot reach the game server.\n\n"
                f"Error: {exc.code} — {str(exc)[:150]}\n\n"
                f"Make sure you ran `python main.py --local` (not just --only bot). "
                f"Type /status to diagnose. You can retry by sending the password again.",
                reply_markup=main_menu_keyboard(),
            )
            return
        # Other API error (e.g. validation) — clear state.
        await state.clear()
        await message.answer(
            _("errors.error_with_message", locale=locale, message=str(exc)),
            reply_markup=main_menu_keyboard(),
        )
        return
    except Exception as exc:  # noqa: BLE001
        # Unexpected error — DON'T clear state so the user can retry.
        # Show the actual error type and message so the user (and
        # developer) can diagnose what's wrong. Previously this showed
        # a generic "Cannot reach the game server" which hid the real
        # cause (e.g. KeyError from a malformed API response, an
        # import error, a Python 3.14 compatibility issue, etc.).
        log.exception("bot.register.failed", error=str(exc))
        exc_type = type(exc).__name__
        exc_msg = str(exc)[:200] or "(no message)"
        await message.answer(
            f"⚠️ Registration failed.\n\n"
            f"Error: {exc_type}: {exc_msg}\n\n"
            f"Check the server console for the full traceback. "
            f"Type /status to diagnose. You can retry by sending the password again.",
            reply_markup=main_menu_keyboard(),
        )
        return
    # Success — clear state.
    await state.clear()
    safe_name = escape_md(user.full_name)
    # Combine the success message and welcome message into ONE send
    # to reduce network roundtrips (each Telegram API call can take
    # 5-10s on poor networks — 2 calls = 10-20s of blocking).
    combined = (
        _("auth.register_success", locale=locale, username=safe_name)
        + "\n\n"
        + _("auth.welcome_message", locale=locale)
    )
    await safe_send(
        message,
        combined,
        parse_mode="Markdown",
        reply_markup=main_menu_keyboard(),
    )


@router.message(AuthStates.waiting_for_password, _NOT_COMMAND)
async def process_login(message: Message, state: FSMContext, locale: str = "en") -> None:
    """Handle password input during login."""
    password = (message.text or "").strip()
    if not password:
        await message.answer(_("auth.password_empty", locale=locale))
        return
    user = message.from_user
    try:
        await api_client.login(telegram_id=user.id, password=password)
    except NationCraftError as exc:
        if is_transient_error(exc):
            # Network error — DON'T clear state, user can retry.
            await message.answer(
                f"⚠️ Cannot reach the game server.\n\n"
                f"Error: {exc.code} — {str(exc)[:150]}\n\n"
                f"Make sure you ran `python main.py --local` (not just --only bot). "
                f"Type /status to diagnose. You can retry by sending the password again.",
                reply_markup=main_menu_keyboard(),
            )
            return
        # Auth error (wrong password, banned, etc.) — clear state.
        await state.clear()
        await message.answer(
            _("auth.login_failed", locale=locale, message=str(exc)),
            reply_markup=main_menu_keyboard(),
        )
        return
    except Exception as exc:  # noqa: BLE001
        log.exception("bot.login.failed", error=str(exc))
        exc_type = type(exc).__name__
        exc_msg = str(exc)[:200] or "(no message)"
        await message.answer(
            f"⚠️ Login failed.\n\n"
            f"Error: {exc_type}: {exc_msg}\n\n"
            f"Check the server console for the full traceback. "
            f"Type /status to diagnose. You can retry by sending the password again.",
            reply_markup=main_menu_keyboard(),
        )
        return
    # Success — clear state.
    await state.clear()
    await message.answer(
        _("auth.login_success", locale=locale),
        reply_markup=main_menu_keyboard(),
    )


@router.message(AuthStates.waiting_for_old_password, _NOT_COMMAND)
async def process_old_password(message: Message, state: FSMContext, locale: str = "en") -> None:
    """Receive the old password and ask for the new one."""
    old_password = (message.text or "").strip()
    if not old_password:
        await message.answer(_("auth.password_empty", locale=locale))
        return
    await state.update_data(old_password=old_password)
    await state.set_state(AuthStates.waiting_for_new_password_reset)
    await message.answer(_("auth.reset_password_new_prompt", locale=locale))


@router.message(AuthStates.waiting_for_new_password_reset, _NOT_COMMAND)
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
        if is_transient_error(exc):
            await message.answer(
                _("errors.api_unreachable", locale=locale),
                reply_markup=main_menu_keyboard(),
            )
            return
        await state.clear()
        await message.answer(
            _("errors.error_with_message", locale=locale, message=str(exc)),
            reply_markup=main_menu_keyboard(),
        )
        return
    except Exception as exc:  # noqa: BLE001
        log.exception("bot.reset_password.failed", error=str(exc))
        await message.answer(
            _("errors.api_unreachable", locale=locale),
            reply_markup=main_menu_keyboard(),
        )
        return
    await state.clear()
    # The server has revoked all sessions for this player. Drop both the
    # access token AND the refresh token locally — the user must /login again.
    api_client.clear_token(user.id)
    await message.answer(
        _("auth.password_reset_success", locale=locale),
        reply_markup=main_menu_keyboard(),
    )
