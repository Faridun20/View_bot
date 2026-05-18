"""Команда /search — ad-hoc поиск свежих лотов под текущий фильтр.

В отличие от автоматического почасового обхода, /search работает сразу:
обходит подкатегории, идёт сверху списка (новые pid) и присылает первые N,
которые проходят пользовательский фильтр.

Использование:
    /search          — 5 свежих лотов
    /search 10       — 10 свежих лотов (макс. 20)
"""
from __future__ import annotations

import asyncio
import logging

from aiogram import Router
from aiogram.filters import Command, CommandObject
from aiogram.types import Message

from bot import config
from bot.monitor import _fetch_item, _scan_categories, matches
from bot.notifier import send_listing
from bot.storage import init_db

logger = logging.getLogger(__name__)
router = Router(name="search")


DEFAULT_COUNT = 5
MAX_COUNT = 20
# Максимум карточек, которые готовы загрузить ради N совпадений. Если у
# пользователя очень узкий фильтр — лучше остановиться, чем парсить весь
# сайт впустую.
MAX_SCANNED = 100


@router.message(Command("search"))
async def cmd_search(msg: Message, command: CommandObject) -> None:
    n = DEFAULT_COUNT
    if command.args:
        arg = command.args.strip().split()[0]
        if arg.isdigit():
            n = max(1, min(MAX_COUNT, int(arg)))
        else:
            await msg.answer(
                f"Использование: <code>/search [число]</code>\n"
                f"Например: <code>/search 10</code> (макс. {MAX_COUNT})",
                parse_mode="HTML",
            )
            return

    db = init_db(config.DB_PATH)
    f = db.get_filter(msg.chat.id)
    filter_descr = "по вашему фильтру" if not f.is_empty() else "(фильтр не задан — самые свежие)"

    status_msg = await msg.answer(f"🔎 Ищу {n} лотов {filter_descr}…")

    # 1. Обход подкатегорий (8 запросов, ~1 сек после прогрева)
    try:
        found = await asyncio.to_thread(_scan_categories)
    except Exception as e:
        logger.exception("search: ошибка обхода")
        await msg.answer(f"❌ Ошибка обхода: <code>{e}</code>", parse_mode="HTML")
        return

    if not found:
        await msg.answer("Сайт ничего не вернул. Попробуйте позже.")
        return

    # 2. Идём по свежим pid сверху
    sorted_pids = sorted(found.items(), key=lambda x: x[0], reverse=True)

    sent = 0
    scanned = 0
    for pid, cate in sorted_pids:
        if sent >= n or scanned >= MAX_SCANNED:
            break
        scanned += 1
        item = await asyncio.to_thread(_fetch_item, pid)
        if item is None:
            continue
        if not matches(item, f):
            continue
        ok = await send_listing(msg.bot, msg.chat.id, item)
        if ok:
            sent += 1
        # Telegram-rate-limit: 1 msg/sec на чат для send_photo с caption.
        await asyncio.sleep(0.3)

    # 3. Итоговое сообщение
    try:
        await status_msg.delete()
    except Exception:
        pass

    if sent == 0:
        await msg.answer(
            f"😕 Ничего не подошло (проверил {scanned} свежих лотов).\n"
            f"Посмотрите фильтр: /myfilter\n"
            f"Сбросить фильтр: /reset"
        )
    elif sent < n:
        await msg.answer(
            f"Найдено {sent} из {n} — это всё среди {scanned} последних лотов. "
            f"Чтобы получать больше совпадений — расширьте фильтр (/filter)."
        )
    else:
        await msg.answer(f"✅ Прислал {sent} лотов.")
