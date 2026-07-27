"""Callback query handlers — the in-game navigation hub."""
from __future__ import annotations

from aiogram import F, Router
from aiogram.types import CallbackQuery

from nationcraft.bot.api_client import api_client
from nationcraft.bot.keyboards import (
    InlineKeyboardBuilder,
    back_button,
    main_menu_keyboard,
    paginate,
    paginated_keyboard,
)
from nationcraft.core.exceptions import NationCraftError
from nationcraft.core.i18n import _
from nationcraft.core.logging import get_logger

log = get_logger(__name__)


async def _safe_api_call(cb: CallbackQuery, locale: str, coro):
    """Run an API call; on connection error, show a friendly message.

    Returns the result on success, or ``None`` on failure (after
    showing an error to the user).
    """
    try:
        return await coro
    except NationCraftError as exc:
        await cb.message.edit_text(
            _("errors.error_with_message", locale=locale, message=str(exc)),
            reply_markup=main_menu_keyboard(),
        )
        await cb.answer()
        return None
    except Exception as exc:  # noqa: BLE001
        # Network errors (httpx.ConnectError, etc.) land here.
        log.warning("bot.api.connection_error", error=str(exc)[:200])
        await cb.message.edit_text(
            _("errors.api_unreachable", locale=locale),
            reply_markup=main_menu_keyboard(),
        )
        await cb.answer()
        return None


router = Router()


# -------------------- home --------------------

@router.callback_query(F.data == "menu:home")
async def cb_home(cb: CallbackQuery) -> None:
    await cb.message.edit_text(
        "🌍 *NationCraft*\n\nWhat would you like to do?",
        reply_markup=main_menu_keyboard(),
        parse_mode="Markdown",
    )
    await cb.answer()


@router.callback_query(F.data == "noop")
async def cb_noop(cb: CallbackQuery) -> None:
    await cb.answer()


# -------------------- country --------------------

@router.callback_query(F.data == "menu:country")
async def cb_country(cb: CallbackQuery) -> None:
    tid = cb.from_user.id
    try:
        snapshot = await api_client.my_country(tid)
    except NationCraftError as exc:
        await cb.message.edit_text(f"❌ {exc}", reply_markup=main_menu_keyboard())
        await cb.answer()
        return
    if not snapshot:
        kb = InlineKeyboardBuilder()
        kb.button(text="🌍 Pick world & country", callback_data="worlds:p0")
        kb.row(back_button())
        await cb.message.edit_text(
            "You don't have a country yet. Pick one to start playing.",
            reply_markup=kb.as_markup(),
        )
        await cb.answer()
        return
    c = snapshot["country"]
    text = (
        f"{c['flag_emoji']} *{c['name']}* ({c['code']})\n\n"
        f"👥 Population: {c['population']:,}\n"
        f"💰 Treasury: {c['treasury']:,.0f}\n"
        f"❤ Approval: {c['approval']:.1f}%\n"
        f"🛡 Stability: {c['stability']:.1f}%\n"
        f"🎓 Education: {c['education']:.1f}%\n"
        f"🏥 Healthcare: {c['healthcare']:.1f}%\n"
        f"⚡ Electricity balance: {c['electricity_balance']:.0f}\n\n"
        "📦 *Resources*:\n"
        + "\n".join(f"  {r['key']}: {r['amount']:.1f}" for r in snapshot["resources"])
    )
    kb = InlineKeyboardBuilder()
    kb.button(text="🏭 Buildings", callback_data="menu:production")
    kb.button(text="🛡 Units", callback_data="menu:military")
    kb.button(text="🎯 Missions", callback_data="menu:missions")
    kb.adjust(2)
    kb.row(back_button())
    await cb.message.edit_text(text, reply_markup=kb.as_markup(), parse_mode="Markdown")
    await cb.answer()


# -------------------- worlds & country selection --------------------

@router.callback_query(F.data.startswith("worlds:"))
async def cb_worlds(cb: CallbackQuery) -> None:
    tid = cb.from_user.id
    try:
        worlds = await api_client.list_worlds(tid)
    except NationCraftError as exc:
        await cb.message.edit_text(f"❌ {exc}")
        await cb.answer()
        return
    page_idx = int(cb.data.split(":p")[1]) if ":p" in cb.data else 0
    page = paginate(worlds, page_idx, page_size=5)
    kb = paginated_keyboard(
        page,
        item_button=lambda w: (f"🌍 {w['name']} ({w['player_count']}/{w['player_capacity']})", f"world:{w['id']}"),
        page_callback_prefix="worlds",
        back_target="menu:country",
    )
    await cb.message.edit_text("🌍 *Choose a world*", reply_markup=kb, parse_mode="Markdown")
    await cb.answer()


@router.callback_query(F.data.startswith("world:"))
async def cb_world_detail(cb: CallbackQuery) -> None:
    tid = cb.from_user.id
    world_id = int(cb.data.split(":")[1])
    try:
        countries = await api_client.list_available_countries(tid, world_id)
    except NationCraftError as exc:
        await cb.message.edit_text(f"❌ {exc}")
        await cb.answer()
        return
    if not countries:
        await cb.message.edit_text(
            "No countries available in this world.",
            reply_markup=main_menu_keyboard(),
        )
        await cb.answer()
        return
    page_idx = 0
    page = paginate(countries, page_idx, page_size=8)
    kb = paginated_keyboard(
        page,
        item_button=lambda c: (f"{c['flag_emoji']} {c['name']} ({c['code']})", f"sel:{world_id}:{c['code']}"),
        page_callback_prefix=f"worldlist:{world_id}",
        back_target="worlds:p0",
    )
    await cb.message.edit_text("🏳 *Pick your country*", reply_markup=kb, parse_mode="Markdown")
    await cb.answer()


@router.callback_query(F.data.startswith("sel:"))
async def cb_select_country(cb: CallbackQuery) -> None:
    tid = cb.from_user.id
    _, world_id, code = cb.data.split(":")
    try:
        result = await api_client.select_country(tid, int(world_id), code)
    except NationCraftError as exc:
        await cb.message.answer(f"❌ {exc}")
        await cb.answer()
        return
    await cb.message.edit_text(
        f"✅ You are now the ruler of *{result['name']}* {result['flag_emoji']}!",
        parse_mode="Markdown",
        reply_markup=main_menu_keyboard(),
    )
    await cb.answer()


# -------------------- production --------------------

@router.callback_query(F.data == "menu:production")
async def cb_production(cb: CallbackQuery) -> None:
    tid = cb.from_user.id
    try:
        buildings = await api_client.list_buildings(tid)
    except NationCraftError as exc:
        await cb.message.edit_text(f"❌ {exc}")
        await cb.answer()
        return
    if not buildings:
        await cb.message.edit_text(
            "🏭 No buildings yet. Use /build to construct one.",
            reply_markup=main_menu_keyboard(),
        )
        await cb.answer()
        return
    text = "🏭 *Your buildings*\n\n" + "\n".join(
        f"  • {b['key']} Lv{b['level']} — {b['status']}" for b in buildings
    )
    kb = InlineKeyboardBuilder()
    kb.row(back_button("menu:country"))
    await cb.message.edit_text(text, reply_markup=kb.as_markup(), parse_mode="Markdown")
    await cb.answer()


# -------------------- military --------------------

@router.callback_query(F.data == "menu:military")
async def cb_military(cb: CallbackQuery) -> None:
    tid = cb.from_user.id
    try:
        units = await api_client.list_units(tid)
        wars = await api_client.list_wars(tid)
    except NationCraftError as exc:
        await cb.message.edit_text(f"❌ {exc}")
        await cb.answer()
        return
    text = "🛡 *Military*\n\n*Units:*\n" + (
        "\n".join(f"  • {u['key']}: {u['count']} ({u['state']})" for u in units)
        if units else "  (none)"
    )
    text += "\n\n*Active wars:*\n" + (
        "\n".join(f"  • War #{w['id']} vs {'#'+str(w['defender_id'])} — {w['status']}" for w in wars)
        if wars else "  (peace)"
    )
    kb = InlineKeyboardBuilder()
    kb.button(text="🆕 Train units", callback_data="train:p0")
    kb.row(back_button("menu:country"))
    await cb.message.edit_text(text, reply_markup=kb.as_markup(), parse_mode="Markdown")
    await cb.answer()


@router.callback_query(F.data.startswith("train:"))
async def cb_train_list(cb: CallbackQuery) -> None:
    """List trainable unit types from static game data."""
    from nationcraft.core.config import game_data
    units = list(game_data.units.values())
    page_idx = int(cb.data.split(":p")[1]) if ":p" in cb.data else 0
    page = paginate(units, page_idx, page_size=8)
    kb = paginated_keyboard(
        page,
        item_button=lambda u: (f"🎖 {u.name}", f"train1:{u.key}"),
        page_callback_prefix="train",
        back_target="menu:military",
    )
    await cb.message.edit_text("🎖 *Choose a unit to train*", reply_markup=kb, parse_mode="Markdown")
    await cb.answer()


@router.callback_query(F.data.startswith("train1:"))
async def cb_train_choose_count(cb: CallbackQuery) -> None:
    key = cb.data.split(":")[1]
    kb = InlineKeyboardBuilder()
    for n in [1, 5, 10, 50, 100]:
        kb.button(text=f"x{n}", callback_data=f"train2:{key}:{n}")
    kb.adjust(3)
    kb.row(back_button("train:p0"))
    await cb.message.edit_text(f"Choose count for *{key}*:", reply_markup=kb.as_markup(), parse_mode="Markdown")
    await cb.answer()


@router.callback_query(F.data.startswith("train2:"))
async def cb_train_confirm(cb: CallbackQuery) -> None:
    tid = cb.from_user.id
    _, key, count = cb.data.split(":")
    try:
        result = await api_client.train(tid, key, int(count))
        await cb.message.edit_text(
            f"✅ Trained {count} × {key}.\nTotal: {result['total']}",
            reply_markup=main_menu_keyboard(),
        )
    except NationCraftError as exc:
        await cb.message.edit_text(f"❌ {exc}", reply_markup=main_menu_keyboard())
    await cb.answer()


# -------------------- research --------------------

@router.callback_query(F.data == "menu:research")
async def cb_research(cb: CallbackQuery) -> None:
    from nationcraft.core.config import game_data
    techs = list(game_data.techs.values())
    page_idx = 0
    page = paginate(techs, page_idx, page_size=8)
    kb = paginated_keyboard(
        page,
        item_button=lambda t: (f"🧪 {t.name} (T{t.tier})", f"res1:{t.key}"),
        page_callback_prefix="researchlist",
        back_target="menu:home",
    )
    await cb.message.edit_text("🧪 *Research tree*", reply_markup=kb, parse_mode="Markdown")
    await cb.answer()


@router.callback_query(F.data.startswith("res1:"))
async def cb_research_confirm(cb: CallbackQuery) -> None:
    tid = cb.from_user.id
    key = cb.data.split(":")[1]
    try:
        result = await api_client.research(tid, key)
        await cb.message.edit_text(
            f"✅ Research queued: {result['tech']} ({result['status']})",
            reply_markup=main_menu_keyboard(),
        )
    except NationCraftError as exc:
        await cb.message.edit_text(f"❌ {exc}", reply_markup=main_menu_keyboard())
    await cb.answer()


# -------------------- market --------------------

@router.callback_query(F.data == "menu:market")
async def cb_market(cb: CallbackQuery) -> None:
    tid = cb.from_user.id
    try:
        orders = await api_client.list_orders(tid)
    except NationCraftError as exc:
        await cb.message.edit_text(f"❌ {exc}")
        await cb.answer()
        return
    text = "📈 *Your market orders*\n\n" + (
        "\n".join(
            f"  • {o['side'].upper()} {o['quantity']} {o['resource_key']} @ {o['unit_price']} — {o['status']}"
            for o in orders
        ) if orders else "  (no open orders)"
    )
    kb = InlineKeyboardBuilder()
    kb.button(text="➕ Place order", callback_data="market:new")
    kb.row(back_button())
    await cb.message.edit_text(text, reply_markup=kb.as_markup(), parse_mode="Markdown")
    await cb.answer()


@router.callback_query(F.data == "market:new")
async def cb_market_new(cb: CallbackQuery) -> None:
    """Simple quick-trade: pick resource from defaults."""
    from nationcraft.core.config import game_data
    kb = InlineKeyboardBuilder()
    for k in list(game_data.resources.keys())[:8]:
        kb.button(text=k, callback_data=f"market:sell:{k}")
    kb.adjust(2)
    kb.row(back_button("menu:market"))
    await cb.message.edit_text("Select a resource to SELL:", reply_markup=kb.as_markup())
    await cb.answer()


# -------------------- missions --------------------

@router.callback_query(F.data == "menu:missions")
async def cb_missions(cb: CallbackQuery) -> None:
    tid = cb.from_user.id
    try:
        missions = await api_client.list_missions(tid)
    except NationCraftError as exc:
        await cb.message.edit_text(f"❌ {exc}")
        await cb.answer()
        return
    if not missions:
        await cb.message.edit_text("🎯 No missions available.", reply_markup=main_menu_keyboard())
        await cb.answer()
        return
    text = "🎯 *Your missions*\n\n" + "\n".join(
        f"  • [{m['status']}] {m['key']} — {m['progress']*100:.0f}%"
        for m in missions
    )
    kb = InlineKeyboardBuilder()
    for m in missions:
        if m["status"] == "completed":
            kb.button(text=f"Claim {m['key']}", callback_data=f"claim:{m['id']}")
    kb.adjust(2)
    kb.row(back_button())
    await cb.message.edit_text(text, reply_markup=kb.as_markup(), parse_mode="Markdown")
    await cb.answer()


@router.callback_query(F.data.startswith("claim:"))
async def cb_claim(cb: CallbackQuery) -> None:
    tid = cb.from_user.id
    mission_id = int(cb.data.split(":")[1])
    try:
        result = await api_client.claim_mission(tid, mission_id)
        rewards = result.get("rewards", {})
        reward_text = "\n".join(f"  +{v} {k}" for k, v in rewards.items())
        await cb.message.edit_text(
            f"🎉 Mission claimed!\nRewards:\n{reward_text}",
            reply_markup=main_menu_keyboard(),
        )
    except NationCraftError as exc:
        await cb.message.edit_text(f"❌ {exc}", reply_markup=main_menu_keyboard())
    await cb.answer()


# -------------------- rankings --------------------

@router.callback_query(F.data == "menu:rankings")
async def cb_rankings(cb: CallbackQuery) -> None:
    tid = cb.from_user.id
    try:
        snapshot = await api_client.my_country(tid)
        if not snapshot:
            await cb.message.edit_text("Pick a country first.", reply_markup=main_menu_keyboard())
            await cb.answer()
            return
        world_id = snapshot["country"]["world_id"]
        rankings = await api_client.rankings(tid, world_id, "population")
    except NationCraftError as exc:
        await cb.message.edit_text(f"❌ {exc}")
        await cb.answer()
        return
    text = "📊 *World rankings (by population)*\n\n" + "\n".join(
        f"  {r['rank']}. {r['country_name']} — {int(r['score']):,}"
        for r in rankings[:10]
    )
    kb = InlineKeyboardBuilder()
    kb.row(back_button())
    await cb.message.edit_text(text, reply_markup=kb.as_markup(), parse_mode="Markdown")
    await cb.answer()


# -------------------- notifications --------------------

@router.callback_query(F.data == "menu:notifications")
async def cb_notifications(cb: CallbackQuery) -> None:
    tid = cb.from_user.id
    try:
        notifs = await api_client.list_notifications(tid, limit=20)
    except NationCraftError as exc:
        await cb.message.edit_text(f"❌ {exc}")
        await cb.answer()
        return
    if not notifs:
        await cb.message.edit_text("🔔 No notifications.", reply_markup=main_menu_keyboard())
        await cb.answer()
        return
    text = "🔔 *Recent notifications*\n\n" + "\n\n".join(
        f"[{n['level'].upper()}] *{n['title']}*\n{n['body']}"
        for n in notifs[:10]
    )
    kb = InlineKeyboardBuilder()
    kb.row(back_button())
    await cb.message.edit_text(text, reply_markup=kb.as_markup(), parse_mode="Markdown")
    await cb.answer()


# -------------------- settings --------------------

def _language_label(code: str) -> str:
    return {"en": "🇬🇧 English", "fa": "🇮🇷 فارسی"}.get(code, code)


@router.callback_query(F.data == "panel:reset_password")
async def cb_panel_reset_password(cb: CallbackQuery, state, locale: str = "en") -> None:
    """Trigger the /resetpassword flow from the panel button."""
    from nationcraft.bot.handlers.states.auth import AuthStates
    from nationcraft.core.i18n import _
    user = cb.from_user
    if not api_client.get_token(user.id):
        await cb.message.answer(_("auth.must_login_first", locale=locale))
        await cb.answer()
        return
    await state.set_state(AuthStates.waiting_for_old_password)
    await cb.message.answer(_("auth.reset_password_old_prompt", locale=locale))
    await cb.answer()


@router.callback_query(F.data == "menu:settings")
async def cb_settings(cb: CallbackQuery, locale: str = "en") -> None:
    from nationcraft.core.config import settings as app_settings
    from nationcraft.core.i18n import _
    kb = InlineKeyboardBuilder()
    for loc in app_settings.supported_locales_list:
        label = f"✓ {_language_label(loc)}" if loc == locale else _language_label(loc)
        kb.button(text=label, callback_data=f"lang:{loc}")
    kb.adjust(2)
    kb.row(back_button())
    await cb.message.edit_text(
        f"⚙ *{_('menu.settings', locale=locale)}*",
        reply_markup=kb.as_markup(),
        parse_mode="Markdown",
    )
    await cb.answer()


@router.callback_query(F.data.startswith("lang:"))
async def cb_language(cb: CallbackQuery, locale: str = "en") -> None:
    """Persist the new locale via the API, then confirm in the new language."""
    from nationcraft.core.i18n import _
    new_locale = cb.data.split(":")[1]
    tid = cb.from_user.id

    # If the user is authenticated, persist the locale to the backend.
    if api_client.get_token(tid):
        try:
            await api_client.set_locale(tid, new_locale)
        except NationCraftError as exc:
            await cb.answer(
                _("errors.error_with_message", locale=locale, message=str(exc)),
                show_alert=True,
            )
            return
        except Exception:  # noqa: BLE001
            # Network error — still update locally so the UX feels responsive.
            pass

    # Invalidate the middleware's locale cache so the new locale is used
    # immediately on the next message.
    from nationcraft.bot.app import _auth_middleware
    if _auth_middleware is not None:
        _auth_middleware.invalidate_locale(tid)

    # Confirm in the NEW locale.
    await cb.message.edit_text(
        f"🌐 *{_('language.set_to', locale=new_locale, language=_language_label(new_locale))}*",
        reply_markup=main_menu_keyboard(),
        parse_mode="Markdown",
    )
    await cb.answer()


# -------------------- diplomacy (placeholder list) --------------------

@router.callback_query(F.data == "menu:diplomacy")
async def cb_diplomacy(cb: CallbackQuery) -> None:
    await cb.message.edit_text(
        "🤝 Diplomacy menu is reachable through country context "
        "(tap a country on the world map).",
        reply_markup=main_menu_keyboard(),
    )
    await cb.answer()
