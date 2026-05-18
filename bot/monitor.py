"""Логика мониторинга: периодический обход → парсинг → фильтрация → рассылка.

Точка входа — функция `run_scan(bot, db)`.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Iterable

from aiogram import Bot

from bot import config
from bot.notifier import send_listing
from bot.scraper import get_session, parse_item_page, parse_listing_page
from bot.scraper.models import (
    EXCAVATOR_SUBCATEGORIES,
    Listing,
    looks_like_parts,
    target_subcategories,
)
from bot.storage.db import DB, UserFilter

logger = logging.getLogger(__name__)


# ---------- сетевые операции (sync, в to_thread) ---------------------------

def _scan_categories() -> dict[int, str]:
    """Обходит подкатегории экскаваторов (без запчастей, если так настроено).

    Возвращает {pid: cate_code}.
    """
    sess = get_session()
    found: dict[int, str] = {}
    for cate_code in target_subcategories(include_parts=config.INCLUDE_PARTS):
        url = f"/sub8_1_s.html?cate_code={cate_code}&limit=70&page=1"
        try:
            resp = sess.get(url)
            for prev in parse_listing_page(resp.text, cate_code=cate_code):
                # Если pid уже встретился в другой подкатегории — оставляем
                # ту, где впервые увидели (порядок обхода).
                found.setdefault(prev.pid, cate_code)
        except Exception as e:
            logger.exception("Ошибка обхода cate_code=%s: %s", cate_code, e)
    return found


def _fetch_item(pid: int) -> Listing | None:
    sess = get_session()
    try:
        resp = sess.get(f"/sub8_1_vvv.html?pid={pid}")
        return parse_item_page(resp.text, pid)
    except Exception as e:
        logger.exception("Ошибка загрузки карточки pid=%s: %s", pid, e)
        return None


# ---------- фильтрация (чистая Python-логика) ------------------------------

def _year_int(year_raw: str | None) -> int | None:
    if not year_raw:
        return None
    digits = year_raw[:4]
    return int(digits) if digits.isdigit() else None


def matches(item: Listing, f: UserFilter) -> bool:
    # Жёсткое правило: если запчасти/навесное в глобальной настройке
    # отключены, такие лоты не должны попадать ни в /search, ни в рассылку,
    # даже если каким-то образом просочились в карточку (бывает, что
    # продавец публикует запчасть в подкатегории «настоящих» машин).
    if not config.INCLUDE_PARTS and looks_like_parts(item.category_path):
        return False
    if f.manufacturer and (item.manufacturer or "").strip() != f.manufacturer.strip():
        return False
    if f.year_from or f.year_to:
        y = _year_int(item.year)
        if y is None:
            # Без года — пропускаем, если фильтр по году выставлен.
            return False
        if f.year_from and y < f.year_from:
            return False
        if f.year_to and y > f.year_to:
            return False
    if f.price_max_won and item.price_won and item.price_won > f.price_max_won:
        return False
    if f.hours_max and item.hours and item.hours > f.hours_max:
        return False
    if f.keyword:
        kw = f.keyword.strip().lower()
        haystack = " ".join([
            item.model or "", item.description or "",
            item.manufacturer or "",
        ]).lower()
        if kw not in haystack:
            return False
    return True


# ---------- основной цикл --------------------------------------------------

async def run_scan(bot: Bot, db: DB) -> None:
    """Один цикл сканирования: обход → новые лоты → рассылка подходящим."""
    logger.info("Сканирование начато")

    found = await asyncio.to_thread(_scan_categories)
    logger.info("Найдено %d уникальных лотов в первых страницах подкатегорий", len(found))

    if not found:
        logger.warning("Ничего не найдено — возможно, сайт недоступен")
        return

    # Берём только pid, которых нет в seen_pids
    new_pids: list[tuple[int, str]] = []
    for pid, cate in sorted(found.items(), reverse=True):  # сначала свежие
        if not db.is_seen(pid):
            new_pids.append((pid, cate))

    if not new_pids:
        logger.info("Новых лотов нет")
        return

    logger.info("Новых лотов: %d", len(new_pids))

    users = db.active_users()
    user_filters: dict[int, UserFilter] = {u: db.get_filter(u) for u in users}
    # Счётчик отправок в этом прогоне на пользователя — защита от спама.
    sent_in_run: dict[int, int] = {u: 0 for u in users}

    for pid, cate in new_pids:
        item = await asyncio.to_thread(_fetch_item, pid)
        if item is None:
            continue

        # помечаем виденным сразу после успешной загрузки карточки
        db.mark_seen(pid, cate)

        # рассылка тем, у кого фильтр совпал и кому ещё не отправляли
        for chat_id in users:
            if sent_in_run[chat_id] >= config.MAX_NOTIFICATIONS_PER_RUN:
                continue
            f = user_filters[chat_id]
            if not matches(item, f):
                continue
            if db.was_sent(chat_id, pid):
                continue
            ok = await send_listing(bot, chat_id, item)
            if ok:
                db.mark_sent(chat_id, pid)
                sent_in_run[chat_id] += 1
            # Telegram-rate-limit: 30 сообщений/сек глобально, 1/сек на чат.
            await asyncio.sleep(0.05)

    logger.info("Сканирование завершено: отправлено %s", sum(sent_in_run.values()))


async def seed_seen(db: DB, *, take: int) -> None:
    """Первый запуск: помечаем последние N лотов как «виденные», чтобы не
    высыпать всю историю в чаты при первом старте."""
    if db.seen_count() > 0:
        logger.info("seed_seen: пропускаю, в БД уже %d виденных", db.seen_count())
        return
    logger.info("seed_seen: помечаю последние %d лотов как виденные", take)
    found = await asyncio.to_thread(_scan_categories)
    # Берём top-N по pid
    items = sorted(found.items(), key=lambda x: x[0], reverse=True)[:take]
    added = db.mark_seen_bulk(items)
    logger.info("seed_seen: добавлено %d записей", added)
