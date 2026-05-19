"""Команда /search — ad-hoc поиск свежих лотов под текущий фильтр.

В отличие от автоматического почасового обхода, /search работает сразу:
обходит подкатегории, идёт сверху списка (новые pid) и присылает первые N,
которые проходят пользовательский фильтр.

Использование:
    /search          — 5 свежих лотов, ещё не присылавшихся в этом чате
    /search 10       — 10 (макс. 20)
    /search all      — 5 свежих, ИГНОРИРУЯ историю (можно увидеть повторы)
    /search all 10   — то же, но 10
"""
from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, Router
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
    """Грубая отсечка по тому, что видно в превью БЕЗ загрузки карточки.

    Возвращает False, только если ТОЧНО не подходит — иначе True.
    Отсекаем по: подкатегории (cate_code), мин/макс цене, грейду.
    """
    if f.subcategories and prev.cate_code and prev.cate_code not in set(f.subcategories):
        return False

    # Цена — есть в превью списка
    if (f.price_max_won or f.price_min_won) and prev.price_raw:
        won = _parse_price(prev.price_raw)
        if won is not None:
            if f.price_max_won and won > f.price_max_won:
                return False
            if f.price_min_won and won < f.price_min_won:
                return False

    # Грейд тоже виден в превью
    if f.min_grade and prev.grade:
        from bot.scraper.models import grade_rank
        if grade_rank(prev.grade) < f.min_grade:
            return False

    # Фото — если знаем, что в превью миниатюра-заглушка, можно сразу отсечь.
    if f.require_photo and prev.has_photo is False:
        return False

    return True


@router.message(Command("search"))
async def cmd_search(msg: Message, command: CommandObject) -> None:
    # Парсим аргументы: '/search', '/search 10', '/search all', '/search all 10'
    n = DEFAULT_COUNT
    show_all = False
    parts = (command.args or "").strip().split()
    if parts and parts[0].lower() == "all":
        show_all = True
        parts = parts[1:]
    if parts:
        if parts[0].isdigit():
            n = max(1, min(MAX_COUNT, int(parts[0])))
        else:
            await msg.answer(
                "Использование:\n"
                "<code>/search</code> или <code>/search 10</code> — N свежих, "
                "ещё не присылавшихся\n"
                "<code>/search all</code> или <code>/search all 10</code> — "
                "игнорируя историю\n\n"
                f"Максимум {MAX_COUNT} за раз.",
                parse_mode="HTML",
            )
            return
    await do_search(msg.bot, msg.chat.id, n=n, show_all=show_all)


async def do_search(bot: Bot, chat_id: int, *, n: int, show_all: bool) -> None:
    """Общая логика поиска. Вызывается из текстовой команды И из меню-callback."""
    db = init_db(config.DB_PATH)
    f = db.get_filter(chat_id)
    filter_descr = "по вашему фильтру" if not f.is_empty() else "(фильтр не задан — самые свежие)"
    mode_descr = " (включая ранее показанные)" if show_all else ""

    status_msg = await bot.send_message(
        chat_id, f"🔎 Ищу {n} лотов {filter_descr}{mode_descr}…"
    )

    # 1. Обход подкатегорий — даёт {pid: (cate_code, ListingPreview)}.
    # _scan_categories возвращает только {pid: cate_code}, поэтому ниже
    # дублируем обход целиком — у нас есть превью с ценой/моделью.
    try:
        previews = await asyncio.to_thread(_scan_with_previews)
    except Exception as e:
        logger.warning("search: ошибка обхода: %s", e)
        logger.debug("traceback:", exc_info=True)
        await bot.send_message(chat_id, f"❌ Ошибка обхода: <code>{e}</code>", parse_mode="HTML")
        return

    if not previews:
        await bot.send_message(chat_id, "Сайт ничего не вернул. Попробуйте позже.")
        return

    # 2. Идём по свежим pid сверху (preview уже отсортированы)
    budget = max(MIN_BUDGET, n * SCANNED_BUDGET_PER_RESULT)

    sent = 0
    scanned = 0           # сколько превью-карточек просмотрено
    fetched = 0           # сколько полных карточек скачано
    skipped_preview = 0   # отсеяно на этапе превью (цена)
    skipped_seen = 0      # отсеяно как уже отправленные ранее

    for prev in previews:
        if sent >= n or scanned >= budget:
            break
        scanned += 1

        # Сразу скипаем то, что уже присылали — карточку даже не качаем.
        if not show_all and db.was_sent(chat_id, prev.pid):
            skipped_seen += 1
            continue

        # Превью-фильтр (по цене)
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

        ok = await send_listing(bot, chat_id, item)
        if ok:
            sent += 1
            # Запоминаем — чтобы не присылать повторно ни через /search, ни
            # через почасовой мониторинг.
            db.mark_sent(chat_id, prev.pid)
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

    seen_hint = ""
    if skipped_seen:
        seen_hint = (
            f"\n♻️ Пропущено {skipped_seen} уже виденных. "
            f"Чтобы пересмотреть с нуля: <code>/forget</code> "
            f"или <code>/search all {n}</code>."
        )

    if sent == 0:
        await bot.send_message(
            chat_id,
            f"😕 Ничего не подошло.\n"
            f"Просмотрено: <b>{scanned}</b> лотов "
            f"(скачано карточек: {fetched}, отсеяно по цене на превью: "
            f"{skipped_preview}, уже виденных: {skipped_seen}).\n\n"
            f"Посмотрите фильтр: /myfilter\nСбросить фильтр: /reset"
            f"{seen_hint}",
            parse_mode="HTML",
        )
    elif sent < n:
        await bot.send_message(
            chat_id,
            f"Прислал <b>{sent}</b> из {n} — это всё, что нашёл среди "
            f"{scanned} последних лотов.\n\n"
            f"Расширить выборку: /filter, или попробуйте позже — новые лоты "
            f"появляются регулярно.{seen_hint}",
            parse_mode="HTML",
        )
    else:
        await bot.send_message(
            chat_id,
            f"✅ Прислал {sent} лотов "
            f"(просмотрено {scanned}, скачано карточек {fetched}).{seen_hint}",
            parse_mode="HTML",
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
