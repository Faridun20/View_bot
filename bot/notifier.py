"""Формирование текстовой карточки лота и отправка в Telegram.

Используется и из monitor'а (массовые рассылки), и из /test-команды.
"""
from __future__ import annotations

import html
import logging

from aiogram import Bot
from aiogram.enums import ParseMode
from aiogram.exceptions import (
    TelegramAPIError,
    TelegramForbiddenError,
    TelegramRetryAfter,
)
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from bot.scraper.models import EXCAVATOR_SUBCATEGORIES, Listing

logger = logging.getLogger(__name__)


def _listing_kb(pid: int, *, is_fav: bool, seller: str | None) -> InlineKeyboardMarkup:
    """Inline-кнопки под карточкой лота.

    Строка 1: «🔖 В избранное» / «❌ Убрать»  +  «📊 История»
    Строка 2 (опционально): «🚫 Скрывать <продавец>» — если известен seller
    """
    fav_label = "❌ Убрать из избранного" if is_fav else "🔖 В избранное"
    fav_cb = f"fav:del:{pid}" if is_fav else f"fav:add:{pid}"
    rows = [[
        InlineKeyboardButton(text=fav_label, callback_data=fav_cb),
        InlineKeyboardButton(text="📊 История", callback_data=f"hist:{pid}"),
    ]]
    if seller:
        # Telegram callback_data <=64 байт. seller в карточке — короткое имя
        # (대전어태치먼트 и т.п.), но всё равно подстрахуемся: храним только
        # pid и в обработчике достаём seller повторно из карточки.
        rows.append([InlineKeyboardButton(
            text=f"🚫 Скрывать «{seller[:20]}»",
            callback_data=f"bl:seller:{pid}",
        )])
    return InlineKeyboardMarkup(inline_keyboard=rows)


# Алиас для обратной совместимости (favorites.py ещё ссылается на _favorite_kb)
def _favorite_kb(pid: int, is_fav: bool) -> InlineKeyboardMarkup:
    return _listing_kb(pid, is_fav=is_fav, seller=None)


def format_listing(item: Listing) -> str:
    """HTML-форматирование карточки лота для Telegram."""
    def esc(x: str | None) -> str:
        return html.escape(x) if x else "—"

    # Цена: «6,000만원 (≈ 60 млн ВОН)»
    price_line = esc(item.price_raw)
    if item.price_won:
        price_line += f" <i>(≈ {item.price_won // 1_000_000} млн ВОН)</i>"

    # Моточасы: либо число, либо raw, либо «не указаны»
    if item.hours is not None:
        hours_line = f"{item.hours:,} ч".replace(",", " ")
    elif item.hours_raw:
        hours_line = f"<i>{esc(item.hours_raw)}</i>"
    else:
        hours_line = "<i>не указаны</i>"

    # Подкатегория
    cate_human = ""
    if item.category_path:
        cate_human = item.category_path

    lines = [
        f"<b>{esc(item.model)}</b>  ·  {esc(item.grade)}",
        "",
        f"🏭 <b>Производитель:</b> {esc(item.manufacturer)}",
        f"📅 <b>Год:</b> {esc(item.year)}",
        f"⏱ <b>Моточасы:</b> {hours_line}",
        f"💰 <b>Цена:</b> {price_line}",
        f"📍 <b>Регион:</b> {esc(item.region)}",
    ]
    if item.tonnage:
        lines.append(f"⚖️ <b>Тоннаж:</b> {esc(item.tonnage)}")
    if cate_human:
        lines.append(f"🗂 <b>Категория:</b> {esc(cate_human)}")

    lines += [
        "",
        f"👤 <b>Продавец:</b> {esc(item.seller)}",
        f"📞 <b>Телефон:</b> {esc(item.phone)}",
        f"🕐 <b>Размещено:</b> {esc(item.posted_at)}",
    ]
    if item.description:
        desc = item.description.strip()
        if len(desc) > 350:
            desc = desc[:350].rstrip() + "…"
        lines += ["", f"📝 {esc(desc)}"]

    lines += ["", f'🔗 <a href="{item.url}">Открыть на сайте</a>']
    return "\n".join(lines)


async def send_price_drop(bot: Bot, chat_id: int, item: Listing,
                          prev_price_won: int) -> bool:
    """Уведомление о снижении цены на уже виденном лоте."""
    new_won = item.price_won or 0
    if not new_won or new_won >= prev_price_won:
        return False
    delta = prev_price_won - new_won
    pct = round(delta * 100 / prev_price_won) if prev_price_won else 0
    model = item.model or "—"
    grade = item.grade or "—"
    text = (
        f"💰 <b>Снижение цены — {pct}%</b>\n\n"
        f"<b>{html.escape(model)}</b>  ·  {html.escape(grade)}\n"
        f"🏭 {html.escape(item.manufacturer or '—')}\n"
        f"📅 {html.escape(item.year or '—')}\n"
        f"📍 {html.escape(item.region or '—')}\n\n"
        f"Было: <s>{prev_price_won // 1_000_000} млн ВОН</s>\n"
        f"Стало: <b>{new_won // 1_000_000} млн ВОН</b>\n\n"
        f'🔗 <a href="{item.url}">Открыть на сайте</a>'
    )
    try:
        await bot.send_message(
            chat_id, text, parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )
        return True
    except TelegramForbiddenError:
        try:
            from bot import config
            from bot.storage import init_db
            init_db(config.DB_PATH).set_active(chat_id, False)
        except Exception:
            pass
        return False
    except TelegramAPIError as e:
        logger.warning("price_drop: чат %s, pid %s: %s", chat_id, item.pid, e)
        return False


async def send_listing(bot: Bot, chat_id: int, item: Listing,
                       *, tag: str | None = None) -> bool:
    """Отправить карточку лота. True = успех, False = ошибка.

    tag — опциональная плашка над карточкой, например:
      "🆕 Новый лот"            — из почасовой рассылки
      "🔍 По вашему запросу"   — из /search
      "🔖 Из избранного"        — из /favs
      "💰 Снижение цены 12%"   — из price-drop (используется в send_price_drop)
    """
    import asyncio

    from bot import config
    from bot.storage import init_db

    base_text = format_listing(item)
    text = f"<b>{tag}</b>\n\n{base_text}" if tag else base_text
    photo = item.main_photo()
    # Текущее состояние избранного для этого юзера — определяет подпись
    db = init_db(config.DB_PATH)
    kb = _listing_kb(
        item.pid,
        is_fav=db.is_favorite(chat_id, item.pid),
        seller=item.seller,
    )

    async def _do_send() -> None:
        if photo:
            if len(text) <= 1024:
                await bot.send_photo(
                    chat_id=chat_id, photo=photo, caption=text,
                    parse_mode=ParseMode.HTML, reply_markup=kb,
                )
            else:
                await bot.send_photo(chat_id=chat_id, photo=photo)
                await bot.send_message(
                    chat_id=chat_id, text=text,
                    parse_mode=ParseMode.HTML, disable_web_page_preview=True,
                    reply_markup=kb,
                )
        else:
            await bot.send_message(
                chat_id=chat_id, text=text,
                parse_mode=ParseMode.HTML, disable_web_page_preview=True,
                reply_markup=kb,
            )

    try:
        await _do_send()
        return True
    except TelegramForbiddenError:
        # Юзер заблокировал бота / удалил чат — деактивируем, чтобы
        # почасовой мониторинг его пропускал. /start снова активирует.
        logger.info("Чат %s заблокировал бота, деактивирую", chat_id)
        try:
            from bot import config
            from bot.storage import init_db
            init_db(config.DB_PATH).set_active(chat_id, False)
        except Exception:
            logger.exception("Не смог деактивировать %s", chat_id)
        return False
    except TelegramRetryAfter as e:
        # Rate limit — подождём столько, сколько просит Telegram, и попробуем
        # ОДИН раз ещё. Если опять — сдаёмся.
        wait = max(1, int(e.retry_after) + 1)
        logger.warning("RetryAfter %ds для чата %s — ждём и пробуем повторно", wait, chat_id)
        await asyncio.sleep(wait)
        try:
            await _do_send()
            return True
        except TelegramAPIError as e2:
            logger.warning("Повтор не помог: чат %s, лот %s: %s", chat_id, item.pid, e2)
            return False
    except TelegramAPIError as e:
        logger.warning("Не удалось отправить лот %s в чат %s: %s", item.pid, chat_id, e)
        return False
