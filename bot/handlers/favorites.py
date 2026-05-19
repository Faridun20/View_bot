"""Избранные лоты: inline-callback fav:add/del + команда /favs."""
from __future__ import annotations

import asyncio
import logging

from aiogram import F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import Command
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
    """Прислать всё избранное (свежими карточками)."""
    db = init_db(config.DB_PATH)
    pids = db.list_favorites(msg.chat.id, limit=20)
    if not pids:
        await msg.answer(
            "У вас нет избранных лотов.\n\n"
            "Под каждой присланной карточкой есть кнопка <b>🔖 В избранное</b> — "
            "тапайте её, чтобы сохранить интересные лоты сюда.",
            parse_mode="HTML",
        )
        return

    await msg.answer(
        f"🔖 Ваше избранное: <b>{len(pids)}</b> лотов "
        f"(показываю последние {min(len(pids), 20)}).",
        parse_mode="HTML",
    )

    # Парсим карточки актуально с сайта (цены могли поменяться, лот мог
    # быть снят). Делаем последовательно — Telegram любит 1 msg/sec.
    sent = 0
    not_found = []
    for pid in pids:
        item = await asyncio.to_thread(_fetch_item, pid)
        if item is None or not (item.model or item.manufacturer or item.price_raw):
            not_found.append(pid)
            continue
        ok = await send_listing(msg.bot, msg.chat.id, item)
        if ok:
            sent += 1
        await asyncio.sleep(0.3)

    if not_found:
        # Лоты могут быть удалены с сайта или закрыты. Предложим убрать.
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=f"🗑 Убрать {pid} из избранного",
                                  callback_data=f"fav:del:{pid}")]
            for pid in not_found[:5]
        ])
        await msg.answer(
            f"⚠️ Не удалось загрузить {len(not_found)} лотов — возможно, "
            f"они уже сняты с сайта.",
            reply_markup=kb,
        )
