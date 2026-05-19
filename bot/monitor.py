"""Логика мониторинга: периодический обход → парсинг → фильтрация → рассылка.

Точка входа — функция `run_scan(bot, db)`.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Iterable

from aiogram import Bot

from bot import config
from bot.notifier import send_listing, send_price_drop
from bot.scraper import get_session, parse_item_page, parse_listing_page
from bot.scraper.models import (
    EXCAVATOR_SUBCATEGORIES,
    Listing,
    grade_rank,
    looks_like_parts,
    region_matches,
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
            # Сетевой/парсерный сбой по одной подкатегории — продолжаем
            # обход остальных. Без полного traceback (шумно на проде);
            # для отладки — поднимите LOG_LEVEL=DEBUG.
            logger.warning("Ошибка обхода cate_code=%s: %s", cate_code, e)
            logger.debug("traceback:", exc_info=True)
    return found


def _fetch_item(pid: int) -> Listing | None:
    sess = get_session()
    try:
        resp = sess.get(f"/sub8_1_vvv.html?pid={pid}")
        return parse_item_page(resp.text, pid)
    except Exception as e:
        logger.warning("Ошибка загрузки карточки pid=%s: %s", pid, e)
        logger.debug("traceback:", exc_info=True)
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
    # даже если каким-то образом просочились в карточку.
    if not config.INCLUDE_PARTS and looks_like_parts(item.category_path):
        return False

    # Производители (multi)
    if f.manufacturers:
        mfr = (item.manufacturer or "").strip()
        if mfr not in {m.strip() for m in f.manufacturers}:
            return False

    # Подкатегория-размер (multi). Сравниваем по category_path leaf или
    # по cate_code — последний у нас в item.category_path неявный, поэтому
    # используем сверку по корейскому листу через таблицу подкатегорий.
    if f.subcategories:
        from bot.scraper.models import EXCAVATOR_SUBCATEGORIES as _SUBS
        allowed_leaves = {_SUBS[c][0] for c in f.subcategories if c in _SUBS}
        leaf = (item.category_path or "").split(">")[-1].strip()
        if leaf not in allowed_leaves:
            return False

    # Регионы (multi, нечёткое сравнение)
    if not region_matches(item.region, f.regions):
        return False

    # Минимальный грейд
    if f.min_grade:
        if grade_rank(item.grade) < f.min_grade:
            return False

    # Чёрный список ключевых слов
    if f.blacklist_keywords:
        haystack = " ".join([
            item.model or "", item.description or "",
        ]).lower()
        for bk in f.blacklist_keywords:
            if bk and bk.strip().lower() in haystack:
                return False

    # Чёрный список продавцов (상호) — точное совпадение
    if f.blacklist_sellers and item.seller:
        seller = item.seller.strip()
        if any(seller == bs.strip() for bs in f.blacklist_sellers if bs):
            return False

    # Год выпуска
    if f.year_from or f.year_to:
        y = _year_int(item.year)
        if y is None:
            return False
        if f.year_from and y < f.year_from:
            return False
        if f.year_to and y > f.year_to:
            return False

    # Цена
    if f.price_max_won and item.price_won and item.price_won > f.price_max_won:
        return False
    if f.price_min_won and item.price_won and item.price_won < f.price_min_won:
        return False

    # Моточасы
    if f.skip_no_hours and item.hours is None:
        return False
    if f.hours_max and item.hours is not None and item.hours > f.hours_max:
        return False

    # Фото (по полной карточке)
    if f.require_photo and not item.photos:
        return False

    # Ключевое слово (positive search)
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
    total_sent = 0

    for pid, cate in new_pids:
        item = await asyncio.to_thread(_fetch_item, pid)
        if item is None:
            # Сетевая ошибка/HTTP-сбой — НЕ помечаем seen, попробуем в
            # следующем скане (это не «лот битый», а наша проблема).
            continue

        # Canary: если все основные поля пустые — парсер скорее всего
        # сломан под изменения сайта. Логируем и не шлём пустую карточку.
        if not (item.model or item.manufacturer or item.price_raw):
            logger.warning("Пустая карточка pid=%s — парсер мог сломаться", pid)
            db.mark_seen(pid, cate)
            continue

        db.mark_seen(pid, cate)
        # Записываем начальную цену в историю (для дальнейших сравнений).
        if item.price_won:
            db.record_price(pid, item.price_won)

        for chat_id in users:
            f = user_filters[chat_id]
            if not matches(item, f):
                continue
            if db.was_sent(chat_id, pid):
                continue
            ok = await send_listing(bot, chat_id, item, tag="🆕 Новый лот")
            if ok:
                db.mark_sent(chat_id, pid)
                total_sent += 1
            # Telegram-rate-limit: 30 сообщений/сек глобально, 1/сек на чат.
            await asyncio.sleep(0.05)

    # === Проверка изменений цен на уже виденных лотах ===
    # Парсим карточки топ-N свежих pid, которые сейчас на сайте и которые
    # бот раньше уже обрабатывал. Если цена ↓ — уведомляем всех, кому лот
    # ранее отсылали ИЛИ у кого он в избранном.
    price_alerts = await _check_price_drops(bot, db, found)
    logger.info("Сканирование завершено: новых %d, уведомлений о цене %d",
                total_sent, price_alerts)


async def _check_price_drops(bot: Bot, db: DB, found: dict[int, str]) -> int:
    """Перепроверяет топ-N свежих лотов из found, которые уже в seen_pids.

    Возвращает число отправленных уведомлений о снижении цены.
    """
    # Берём только те pid из текущего «found», которые уже знакомы боту.
    candidates = [pid for pid in sorted(found, reverse=True) if db.is_seen(pid)]
    candidates = candidates[: config.PRICE_CHECK_TOP_N]
    if not candidates:
        return 0

    logger.info("price_check: перепроверяю %d уже виденных лотов", len(candidates))
    sent_alerts = 0
    for pid in candidates:
        item = await asyncio.to_thread(_fetch_item, pid)
        if item is None or not item.price_won:
            continue
        # Если в карточке вылез не-машинный лот — пропускаем (защита).
        if not config.INCLUDE_PARTS and looks_like_parts(item.category_path):
            continue
        prev = db.last_price(pid)
        if prev is None:
            db.record_price(pid, item.price_won)
            continue
        if item.price_won == prev:
            continue
        # Цена изменилась — записываем в историю
        db.record_price(pid, item.price_won)
        if item.price_won >= prev:
            continue   # повышение — не уведомляем
        # Снижение → шлём подписанным
        recipients = db.recipients_for_price_drop(pid)
        for chat_id in recipients:
            if not db.is_active(chat_id):
                continue
            ok = await send_price_drop(bot, chat_id, item, prev)
            if ok:
                sent_alerts += 1
            await asyncio.sleep(0.05)
    return sent_alerts


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
