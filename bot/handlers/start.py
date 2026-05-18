"""Базовые команды: /start, /stop, /help, /test, /status."""
from __future__ import annotations

import asyncio
import logging

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import Message

from bot import config
from bot.notifier import send_listing
from bot.scraper import get_session, parse_item_page, parse_listing_page
from bot.scraper.models import EXCAVATOR_SUBCATEGORIES
from bot.storage import init_db

logger = logging.getLogger(__name__)
router = Router(name="start")


HELP_TEXT = (
    "<b>Мониторинг 그린중기 (4396200.com)</b>\n\n"
    "Бот следит за новыми объявлениями в категории <b>«Экскаваторы»</b> и присылает "
    "карточку каждого нового лота, подходящего под ваш фильтр.\n\n"
    "<b>Команды:</b>\n"
    "/start — подписаться\n"
    "/stop — отписаться\n"
    "/filter — настроить фильтр (производитель, год, цена, моточасы, ключевое слово)\n"
    "/myfilter — посмотреть текущий фильтр\n"
    "/reset — сбросить фильтр (тогда шлются все новые лоты)\n"
    "/search [N] — прямо сейчас прислать N свежих лотов по вашему фильтру "
    "(по умолчанию 5, макс 20)\n"
    "/test — прислать самый свежий лот для проверки\n"
    "/status — статистика бота\n"
    "/help — эта справка\n\n"
    f"Проверка сайта — каждые {config.MONITOR_INTERVAL_MINUTES} минут."
)


@router.message(Command("start"))
async def cmd_start(msg: Message) -> None:
    db = init_db(config.DB_PATH)
    db.upsert_user(msg.chat.id, msg.from_user.username if msg.from_user else None)
    await msg.answer(
        "✅ Подписка активна.\n\n" + HELP_TEXT,
        parse_mode="HTML", disable_web_page_preview=True,
    )


@router.message(Command("stop"))
async def cmd_stop(msg: Message) -> None:
    db = init_db(config.DB_PATH)
    db.deactivate_user(msg.chat.id)
    await msg.answer("🛑 Подписка приостановлена. /start — чтобы возобновить.")


@router.message(Command("help"))
async def cmd_help(msg: Message) -> None:
    await msg.answer(HELP_TEXT, parse_mode="HTML", disable_web_page_preview=True)


@router.message(Command("status"))
async def cmd_status(msg: Message) -> None:
    db = init_db(config.DB_PATH)
    text = (
        f"<b>Статистика</b>\n"
        f"• Активных подписчиков: {len(db.active_users())}\n"
        f"• Лотов в истории: {db.seen_count()}"
    )
    await msg.answer(text, parse_mode="HTML")


@router.message(Command("test"))
async def cmd_test(msg: Message) -> None:
    """Прислать самый свежий лот с сайта — для проверки рендеринга."""
    await msg.answer("Ищу свежий лот…")
    try:
        item = await asyncio.to_thread(_fetch_latest)
    except Exception as e:
        logger.exception("test: ошибка")
        await msg.answer(f"❌ Ошибка: <code>{e}</code>", parse_mode="HTML")
        return

    if item is None:
        await msg.answer("Не удалось получить лот — проверьте логи.")
        return

    await send_listing(msg.bot, msg.chat.id, item)


def _fetch_latest():
    """Берёт самый свежий pid из первой подкатегории и парсит карточку."""
    sess = get_session()
    # Самые активные подкатегории — навесное (100106) и крупные экскаваторы.
    for cate_code in ("100106", "100100", "100101", "100102", "100104"):
        resp = sess.get(f"/sub8_1_s.html?cate_code={cate_code}&limit=70&page=1")
        previews = parse_listing_page(resp.text, cate_code=cate_code)
        if previews:
            top = previews[0]
            r = sess.get(f"/sub8_1_vvv.html?pid={top.pid}")
            return parse_item_page(r.text, top.pid)
    return None
