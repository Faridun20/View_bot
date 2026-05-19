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
    added = db.add_favorite(cb.message.chat.id, pid)
    # Обновим клавиатуру под сообщением, чтобы кнопка превратилась в «Убрать»
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
            "pid лота виден в ссылке «Открыть на сайте» в карточке "
            "(после <code>?pid=</code>).",
            parse_mode="HTML",
        )
        return
    pid = int(arg)
    db = init_db(config.DB_PATH)
    rows = db.price_history(pid, limit=50)
    if not rows:
        await msg.answer(
            f"📊 По pid <b>{pid}</b> история цен пуста.\n"
            f"Бот записывает цену при первом появлении лота в каталоге и "
            f"при каждом изменении.",
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
    await msg.answer("\n".join(lines), parse_mode="HTML",
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


@router.message(Command("favs"))
async def cmd_favs(msg: Message) -> None:
    await show_favorites(msg.bot, msg.chat.id)


async def show_favorites(bot, chat_id: int) -> None:
    """Прислать все избранные лоты пользователя (актуально с сайта).

    Вынесено из cmd_favs, чтобы вызывать и из callback-кнопок главного меню.
    """
    db = init_db(config.DB_PATH)
    pids = db.list_favorites(chat_id, limit=20)
    if not pids:
        await bot.send_message(
            chat_id,
            "У вас нет избранных лотов.\n\n"
            "Под каждой присланной карточкой есть кнопка <b>🔖 В избранное</b> — "
            "тапайте её, чтобы сохранить интересные лоты сюда.",
            parse_mode="HTML",
        )
        return

    await bot.send_message(
        chat_id,
        f"🔖 Ваше избранное: <b>{len(pids)}</b> лотов "
        f"(показываю последние {min(len(pids), 20)}).",
        parse_mode="HTML",
    )

    sent = 0
    not_found = []
    for pid in pids:
        item = await asyncio.to_thread(_fetch_item, pid)
        if item is None or not (item.model or item.manufacturer or item.price_raw):
            not_found.append(pid)
            continue
        ok = await send_listing(bot, chat_id, item, tag="🔖 Из избранного")
        if ok:
            sent += 1
        await asyncio.sleep(0.3)

    if not_found:
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=f"🗑 Убрать {pid} из избранного",
                                  callback_data=f"fav:del:{pid}")]
            for pid in not_found[:5]
        ])
        await bot.send_message(
            chat_id,
            f"⚠️ Не удалось загрузить {len(not_found)} лотов — возможно, "
            f"они уже сняты с сайта.",
            reply_markup=kb,
        )
