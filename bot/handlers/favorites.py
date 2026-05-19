"""Избранные лоты: inline-callback fav:add/del + команда /favs + /history."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime

from aiogram import F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import Command, CommandObject
from aiogram.types import (
    CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message,
)

from bot import config
from bot.monitor import _fetch_item
from bot.notifier import _favorite_kb, send_listing
from bot.storage import init_db

logger = logging.getLogger(__name__)
router = Router(name="favorites")


@router.callback_query(F.data.startswith("fav:add:"))
async def cb_fav_add(cb: CallbackQuery) -> None:
    pid = int(cb.data.split(":")[2])
    db = init_db(config.DB_PATH)
    # Попробуем достать модель из карточки, чтобы потом /favs показывал
    # компактный список вместо одних pid'ов. Если карточку не достали — не страшно.
    model: str | None = None
    try:
        item = await asyncio.to_thread(_fetch_item, pid)
        if item:
            model = item.model
    except Exception:
        pass
    added = db.add_favorite(cb.message.chat.id, pid, model=model)
    try:
        await cb.message.edit_reply_markup(reply_markup=_favorite_kb(pid, True))
    except TelegramAPIError:
        pass
    await cb.answer("🔖 Добавлено в избранное" if added else "Уже было в избранном",
                    show_alert=False)


@router.callback_query(F.data.startswith("fav:del:"))
async def cb_fav_del(cb: CallbackQuery) -> None:
    pid = int(cb.data.split(":")[2])
    db = init_db(config.DB_PATH)
    removed = db.remove_favorite(cb.message.chat.id, pid)
    try:
        await cb.message.edit_reply_markup(reply_markup=_favorite_kb(pid, False))
    except TelegramAPIError:
        pass
    await cb.answer("❌ Убрано из избранного" if removed else "В избранном не было",
                    show_alert=False)


@router.callback_query(F.data.startswith("bl:seller:"))
async def cb_blacklist_seller(cb: CallbackQuery) -> None:
    """Добавить продавца текущей карточки в чёрный список юзера.

    Имя продавца берём заново из карточки сайта — кнопка callback_data
    хранит только pid (лимит 64 байта).
    """
    pid = int(cb.data.split(":")[2])
    item = await asyncio.to_thread(_fetch_item, pid)
    if item is None or not item.seller:
        await cb.answer("Не нашёл продавца в карточке", show_alert=True)
        return
    seller = item.seller.strip()
    db = init_db(config.DB_PATH)
    f = db.get_filter(cb.message.chat.id)
    if seller in f.blacklist_sellers:
        await cb.answer(f"«{seller}» уже в чёрном списке", show_alert=False)
        return
    f.blacklist_sellers = list(f.blacklist_sellers) + [seller]
    db.set_filter(f)
    await cb.answer(
        f"🚫 «{seller}» добавлен в чёрный список. /myfilter — посмотреть.",
        show_alert=True,
    )


@router.message(Command("history"))
async def cmd_history(msg: Message, command: CommandObject) -> None:
    """Показать историю цен лота: /history <pid>"""
    arg = (command.args or "").strip()
    if not arg.isdigit():
        await msg.answer(
            "Использование: <code>/history 9155895</code>\n\n"
            "pid лота виден в ссылке «Открыть на сайте» в карточке. "
            "Удобнее — нажать кнопку <b>📊 История</b> прямо под "
            "карточкой лота.",
            parse_mode="HTML",
        )
        return
    await _send_history(msg.bot, msg.chat.id, int(arg))


@router.callback_query(F.data.startswith("hist:"))
async def cb_history(cb: CallbackQuery) -> None:
    """Кнопка «📊 История» под карточкой лота."""
    pid = int(cb.data.split(":")[1])
    await cb.answer("Открываю историю…")
    await _send_history(cb.bot, cb.message.chat.id, pid)


async def _send_history(bot, chat_id: int, pid: int) -> None:
    """Формирует и шлёт текст истории цен. Используется и /history, и
    кнопкой hist:<pid>."""
    db = init_db(config.DB_PATH)
    rows = db.price_history(pid, limit=50)
    if not rows:
        await bot.send_message(
            chat_id,
            f"📊 По pid <b>{pid}</b> история цен пуста.\n"
            f"Бот записывает цену при первом появлении лота в каталоге и "
            f"при каждом изменении — она появится после следующего scan'а.",
            parse_mode="HTML",
        )
        return

    # rows: [(recorded_at_iso, price_won)] DESC
    lines = [f"📊 <b>История цен лота {pid}</b>\n"]
    prev_price = None
    for ts, price in reversed(rows):     # ASC для красивого графика снизу вверх
        try:
            dt = datetime.fromisoformat(ts).strftime("%d.%m %H:%M")
        except ValueError:
            dt = ts
        if price is None:
            lines.append(f"<code>{dt}</code> — цена не указана")
            continue
        marker = ""
        if prev_price is not None and price != prev_price:
            if price < prev_price:
                pct = round((prev_price - price) * 100 / prev_price)
                marker = f"  ↓ {pct}%"
            else:
                pct = round((price - prev_price) * 100 / prev_price)
                marker = f"  ↑ {pct}%"
        man_won = price // 10_000
        lines.append(f"<code>{dt}</code> — {man_won:,} 만원{marker}".replace(",", " "))
        prev_price = price

    # Текущая = последняя
    if prev_price is not None:
        lines.append(f"\n<b>Сейчас:</b> {prev_price // 10_000:,} 만원".replace(",", " "))

    lines.append(f'\n🔗 <a href="https://www.4396200.com/sub8_1_vvv.html?pid={pid}">'
                 f'Открыть лот на сайте</a>')
    await bot.send_message(chat_id, "\n".join(lines), parse_mode="HTML",
                           disable_web_page_preview=True)


@router.message(Command("unblock_sellers"))
async def cmd_unblock_sellers(msg: Message) -> None:
    """Очистить чёрный список продавцов."""
    db = init_db(config.DB_PATH)
    f = db.get_filter(msg.chat.id)
    if not f.blacklist_sellers:
        await msg.answer("Чёрный список продавцов и так пуст.")
        return
    sellers = list(f.blacklist_sellers)
    f.blacklist_sellers = []
    db.set_filter(f)
    await msg.answer(
        "✅ Разблокировано:\n• " + "\n• ".join(sellers),
    )


FAVS_PER_PAGE = 10


@router.message(Command("favs"))
async def cmd_favs(msg: Message) -> None:
    await show_favorites(msg.bot, msg.chat.id, offset=0)


async def show_favorites(bot, chat_id: int, *, offset: int = 0) -> None:
    """Список избранных — одно сообщение с кликабельными кнопками
    «Открыть <модель>». Pagination по FAVS_PER_PAGE.
    """
    db = init_db(config.DB_PATH)
    total = db.count_favorites(chat_id)
    if total == 0:
        await bot.send_message(
            chat_id,
            "У вас нет избранных лотов.\n\n"
            "Под каждой присланной карточкой есть кнопка <b>🔖 В избранное</b> — "
            "тапайте её, чтобы сохранить интересные лоты сюда.",
            parse_mode="HTML",
        )
        return

    items = db.list_favorites_with_model(chat_id, limit=FAVS_PER_PAGE, offset=offset)

    # Список текстом + кнопки-«открыть» под каждой строкой
    rows: list[list[InlineKeyboardButton]] = []
    text_lines = [f"🔖 <b>Избранное:</b> {total} лотов"]
    if total > FAVS_PER_PAGE:
        first_idx = offset + 1
        last_idx = offset + len(items)
        text_lines.append(f"<i>Показано {first_idx}–{last_idx}</i>")
    text_lines.append("")
    for pid, model in items:
        label = (model or f"лот {pid}")[:30]
        text_lines.append(f"• {label} <code>(pid {pid})</code>")
        rows.append([
            InlineKeyboardButton(text=f"📋 {label[:18]}", callback_data=f"fav:open:{pid}"),
            InlineKeyboardButton(text="📊", callback_data=f"hist:{pid}"),
            InlineKeyboardButton(text="🗑", callback_data=f"fav:del:{pid}"),
        ])

    # Pagination кнопки
    nav: list[InlineKeyboardButton] = []
    if offset > 0:
        prev_off = max(0, offset - FAVS_PER_PAGE)
        nav.append(InlineKeyboardButton(text="← Назад",
                                        callback_data=f"fav:page:{prev_off}"))
    if offset + FAVS_PER_PAGE < total:
        next_off = offset + FAVS_PER_PAGE
        nav.append(InlineKeyboardButton(text="Вперёд →",
                                        callback_data=f"fav:page:{next_off}"))
    if nav:
        rows.append(nav)

    await bot.send_message(
        chat_id,
        "\n".join(text_lines),
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
        disable_web_page_preview=True,
    )


@router.callback_query(F.data.startswith("fav:page:"))
async def cb_favs_page(cb: CallbackQuery) -> None:
    offset = int(cb.data.split(":")[2])
    await cb.answer()
    await show_favorites(cb.bot, cb.message.chat.id, offset=offset)


@router.callback_query(F.data.startswith("fav:open:"))
async def cb_favs_open(cb: CallbackQuery) -> None:
    """Открыть карточку конкретного лота из списка избранного."""
    pid = int(cb.data.split(":")[2])
    await cb.answer("Открываю карточку…")
    item = await asyncio.to_thread(_fetch_item, pid)
    if item is None or not (item.model or item.manufacturer or item.price_raw):
        await cb.message.answer(
            f"⚠️ Не удалось загрузить лот {pid} — возможно, он снят с сайта.\n\n"
            f"Убрать из избранного:",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(text=f"🗑 Убрать {pid}",
                                     callback_data=f"fav:del:{pid}")
            ]]),
        )
        return
    await send_listing(cb.bot, cb.message.chat.id, item, tag="🔖 Из избранного")
