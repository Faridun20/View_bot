"""Формирование текстовой карточки лота и отправка в Telegram.

Используется и из monitor'а (массовые рассылки), и из /test-команды.
"""
from __future__ import annotations

import html
import logging

from aiogram import Bot
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramAPIError

from bot.scraper.models import EXCAVATOR_SUBCATEGORIES, Listing

logger = logging.getLogger(__name__)


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


async def send_listing(bot: Bot, chat_id: int, item: Listing) -> bool:
    """Отправить карточку лота. True = успех, False = ошибка."""
    text = format_listing(item)
    photo = item.main_photo()

    try:
        if photo:
            # caption у фото ограничен 1024 символами — обрезаем, полный текст
            # уйдёт отдельным сообщением только если не влез.
            if len(text) <= 1024:
                await bot.send_photo(
                    chat_id=chat_id, photo=photo, caption=text,
                    parse_mode=ParseMode.HTML,
                )
            else:
                await bot.send_photo(chat_id=chat_id, photo=photo)
                await bot.send_message(
                    chat_id=chat_id, text=text,
                    parse_mode=ParseMode.HTML, disable_web_page_preview=True,
                )
        else:
            await bot.send_message(
                chat_id=chat_id, text=text,
                parse_mode=ParseMode.HTML, disable_web_page_preview=True,
            )
        return True
    except TelegramAPIError as e:
        logger.warning("Не удалось отправить лот %s в чат %s: %s", item.pid, chat_id, e)
        return False
