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
    "<b>👉 Самое удобное:</b> /menu — кнопочный интерфейс для всех действий.\n\n"
    "<b>Команды:</b>\n"
    "/menu — открыть меню (поиск, фильтр, помощь)\n"
    "/start — подписаться\n"
    "/stop — отписаться\n"
    "/filter — настроить фильтр пошагово (без кнопок)\n"
    "/myfilter — посмотреть текущий фильтр\n"
    "/reset — сбросить фильтр (тогда шлются все новые лоты)\n"
    "/search [N] — прислать N свежих лотов по фильтру, <b>исключая ранее показанные</b> "
    "(макс 20, по умолчанию 5)\n"
    "/search all [N] — то же, но <b>с повторами</b> (если хочется пересмотреть)\n"
    "/forget — очистить вашу историю «уже виденных»\n"
    "/test — прислать самый свежий лот для проверки\n"
    "/status — статистика бота\n"
    "/help — эта справка\n\n"
    f"Проверка сайта — каждые {config.MONITOR_INTERVAL_MINUTES} минут.\n"
    f"Запчасти и навесное оборудование: "
    f"{'включены' if config.INCLUDE_PARTS else 'НЕ показываются (только экскаваторы)'}."
)


@router.message(Command("start"))
async def cmd_start(msg: Message) -> None:
    from bot import keyboards  # локальный импорт, чтобы не плодить циклы
    db = init_db(config.DB_PATH)
    db.upsert_user(msg.chat.id, msg.from_user.username if msg.from_user else None)
    await msg.answer(
        "✅ Подписка активна.\n\n"
        "Откройте меню кнопкой ниже или командой /menu.\n"
        "Все команды — в /help.",
        reply_markup=keyboards.main_menu(),
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

    ok = await send_listing(msg.bot, msg.chat.id, item)
    if ok:
        # Помечаем как отправленное — чтобы /search и почасовой мониторинг
        # потом не дублировали этот же лот.
        init_db(config.DB_PATH).mark_sent(msg.chat.id, item.pid)


@router.message(Command("forget"))
async def cmd_forget(msg: Message) -> None:
    """Очистить историю отправленных лотов для пользователя — после этого
    /search снова сможет показать любые свежие лоты."""
    db = init_db(config.DB_PATH)
    removed = db.clear_sent(msg.chat.id)
    if removed:
        await msg.answer(
            f"♻️ История очищена ({removed} лотов забыто).\n"
            f"Теперь /search и почасовой мониторинг могут снова прислать ранее показанные лоты."
        )
    else:
        await msg.answer("История уже пуста — забывать нечего.")


def _fetch_latest():
    """Берёт самый свежий лот среди настоящих экскаваторов и парсит карточку."""
    from bot.scraper.models import target_subcategories
    sess = get_session()
    # Идём по «машинным» подкатегориям — обычно объявления появляются часто
    # в крупных экскаваторах (100100) и мини (100104).
    for cate_code in target_subcategories(include_parts=config.INCLUDE_PARTS):
        resp = sess.get(f"/sub8_1_s.html?cate_code={cate_code}&limit=70&page=1")
        previews = parse_listing_page(resp.text, cate_code=cate_code)
        if previews:
            top = previews[0]
            r = sess.get(f"/sub8_1_vvv.html?pid={top.pid}")
            return parse_item_page(r.text, top.pid)
    return None
