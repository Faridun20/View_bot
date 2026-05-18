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
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import Command, CommandObject
from aiogram.types import Message

from bot import config
from bot.monitor import _fetch_item, _scan_categories, matches
from bot.notifier import send_listing
from bot.scraper.models import ListingPreview
from bot.scraper.parser import _parse_price
from bot.storage import init_db
from bot.storage.db import UserFilter

logger = logging.getLogger(__name__)
router = Router(name="search")


DEFAULT_COUNT = 5
MAX_COUNT = 20
# Сколько превью-карточек разрешено проверить ради N совпадений.
# 25× даёт хорошее покрытие для узких фильтров (n=10 → 250, n=20 → 500),
# но всё равно ограничено: при пустом сайте не зависнем навсегда.
SCANNED_BUDGET_PER_RESULT = 25
MIN_BUDGET = 150
# Раз во сколько проверок обновляем прогресс-сообщение.
PROGRESS_EVERY = 25


def _passes_preview(prev: ListingPreview, f: UserFilter) -> bool:
    """Грубая отсечка по тому, что видно в превью списка БЕЗ загрузки карточки.

    Возвращает False, только если ТОЧНО не подходит, иначе True (надо качать).
    Сейчас умеем отсекать по максимальной цене.
    """
    if f.price_max_won and prev.price_raw:
        won = _parse_price(prev.price_raw)
        if won is not None and won > f.price_max_won:
            return False
    return True


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

    # 1. Обход подкатегорий — даёт {pid: (cate_code, ListingPreview)}.
    # _scan_categories возвращает только {pid: cate_code}, поэтому ниже
    # дублируем обход целиком — у нас есть превью с ценой/моделью.
    try:
        previews = await asyncio.to_thread(_scan_with_previews)
    except Exception as e:
        logger.exception("search: ошибка обхода")
        await msg.answer(f"❌ Ошибка обхода: <code>{e}</code>", parse_mode="HTML")
        return

    if not previews:
        await msg.answer("Сайт ничего не вернул. Попробуйте позже.")
        return

    # 2. Идём по свежим pid сверху (preview уже отсортированы)
    budget = max(MIN_BUDGET, n * SCANNED_BUDGET_PER_RESULT)

    sent = 0
    scanned = 0           # сколько превью-карточек просмотрено
    fetched = 0           # сколько полных карточек скачано
    skipped_preview = 0   # сколько отсеяно ещё на этапе превью

    for prev in previews:
        if sent >= n or scanned >= budget:
            break
        scanned += 1

        # Превью-фильтр
        if not _passes_preview(prev, f):
            skipped_preview += 1
            continue

        # Полная карточка
        item = await asyncio.to_thread(_fetch_item, prev.pid)
        if item is None:
            continue
        fetched += 1
        if not matches(item, f):
            continue

        ok = await send_listing(msg.bot, msg.chat.id, item)
        if ok:
            sent += 1
        # Telegram-rate-limit: 1 msg/sec на чат для send_photo с caption.
        await asyncio.sleep(0.3)

        # Прогресс-апдейт
        if scanned % PROGRESS_EVERY == 0:
            try:
                await status_msg.edit_text(
                    f"🔎 Просмотрено {scanned} / {budget}, "
                    f"найдено {sent} / {n}…"
                )
            except TelegramAPIError:
                pass

    # 3. Итоговое сообщение
    try:
        await status_msg.delete()
    except Exception:
        pass

    if sent == 0:
        await msg.answer(
            f"😕 Ничего не подошло.\n"
            f"Просмотрено: <b>{scanned}</b> лотов "
            f"(скачано карточек: {fetched}, отсеяно по цене на превью: {skipped_preview}).\n\n"
            f"Посмотрите фильтр: /myfilter\nСбросить: /reset",
            parse_mode="HTML",
        )
    elif sent < n:
        await msg.answer(
            f"Прислал <b>{sent}</b> из {n} — это всё, что нашёл среди "
            f"{scanned} последних лотов.\n\n"
            f"Расширить выборку: /filter, или попробуйте позже — новые лоты "
            f"появляются регулярно.",
            parse_mode="HTML",
        )
    else:
        await msg.answer(
            f"✅ Прислал {sent} лотов "
            f"(просмотрено {scanned}, скачано карточек {fetched})."
        )


# ---- helpers --------------------------------------------------------------

def _scan_with_previews() -> list[ListingPreview]:
    """Обходит подкатегории (с учётом INCLUDE_PARTS), возвращает уникальные
    превью по убыванию pid."""
    from bot.scraper import get_session, parse_listing_page
    from bot.scraper.models import target_subcategories

    sess = get_session()
    by_pid: dict[int, ListingPreview] = {}
    for cate_code in target_subcategories(include_parts=config.INCLUDE_PARTS):
        try:
            resp = sess.get(f"/sub8_1_s.html?cate_code={cate_code}&limit=70&page=1")
            for prev in parse_listing_page(resp.text, cate_code=cate_code):
                # Если pid уже встречался — оставляем первое попадание.
                by_pid.setdefault(prev.pid, prev)
        except Exception as e:
            logger.exception("search/_scan_with_previews: cate=%s: %s", cate_code, e)
    return sorted(by_pid.values(), key=lambda p: p.pid, reverse=True)
