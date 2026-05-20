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
    "<b>🚜 Мониторинг экскаваторов — 그린중기 (4396200.com)</b>\n\n"
    "Я слежу за новыми объявлениями и присылаю карточку каждого лота, "
    "подходящего под ваш фильтр.\n\n"
    "<b>👇 Проще всего — кнопки внизу экрана:</b>\n"
    "🔍 Поиск · ⚙️ Фильтр · 🔖 Избранное · 📋 Меню\n\n"
    "<b>Основное</b>\n"
    "/menu — главное меню\n"
    "/search [N] — прислать N свежих лотов (новых, до 20)\n"
    "/search all [N] — то же, но с повторами\n"
    "/favs — избранные лоты\n"
    "/history &lt;pid&gt; — история цен лота\n\n"
    "<b>Настройка</b>\n"
    "/filter — фильтр по шагам\n"
    "/myfilter — показать текущий фильтр\n"
    "/reset — сбросить фильтр\n"
    "/forget — очистить историю «уже виденных»\n"
    "/unblock_sellers — снять блокировку продавцов\n\n"
    "<b>Подписка и прочее</b>\n"
    "/start — подписаться · /stop — пауза\n"
    "/test — прислать самый свежий лот\n"
    "/status — статистика · /cancel — отменить ввод\n\n"
    f"⏱ Проверка сайта — каждые {config.MONITOR_INTERVAL_MINUTES} мин.\n"
    f"🔧 Запчасти и навесное: "
    f"{'показываются' if config.INCLUDE_PARTS else 'скрыты (только экскаваторы)'}."
)


@router.message(Command("start"))
async def cmd_start(msg: Message) -> None:
    from bot import keyboards  # локальный импорт, чтобы не плодить циклы
    db = init_db(config.DB_PATH)
    is_new = db.upsert_user(
        msg.chat.id,
        msg.from_user.username if msg.from_user else None,
    )

    if is_new:
        # Onboarding для новичков. Сразу ставим постоянную клавиатуру внизу —
        # она и будет основным способом навигации.
        first_name = msg.from_user.first_name if msg.from_user else "коллега"
        text = (
            f"👋 Здравствуйте, {esc_html(first_name)}!\n\n"
            f"Я слежу за новыми объявлениями экскаваторов на сайте "
            f"<b>4396200.com (그린중기)</b> — крупном корейском маркетплейсе "
            f"подержанной спецтехники.\n\n"
            f"<b>Как пользоваться:</b>\n"
            f"  1️⃣  <b>⚙️ Фильтр</b> — задайте, что интересует (бренд, год, "
            f"цена, регион…)\n"
            f"  2️⃣  Каждые {config.MONITOR_INTERVAL_MINUTES} мин я пришлю новые "
            f"подходящие лоты\n"
            f"  3️⃣  <b>🔍 Поиск</b> — посмотреть, что есть прямо сейчас\n\n"
            f"👇 Кнопки внизу всегда под рукой. Начните с <b>⚙️ Фильтр</b>."
        )
        await msg.answer(text, parse_mode="HTML",
                         reply_markup=keyboards.reply_keyboard())
    else:
        # Возвращающийся подписчик — возвращаем нижнюю клавиатуру.
        await msg.answer(
            "✅ С возвращением! Подписка активна.\n"
            "Кнопки внизу 👇 или /menu для всех настроек.",
            reply_markup=keyboards.reply_keyboard(),
        )


def esc_html(s: str | None) -> str:
    import html
    return html.escape(s or "")


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
    auto_on = db.is_active(msg.chat.id)
    favs_n = db.count_favorites(msg.chat.id)
    text = (
        f"<b>📊 Статистика</b>\n\n"
        f"{'🔔 Авто-уведомления: ВКЛ' if auto_on else '🔕 Авто-уведомления: ВЫКЛ'}\n"
        f"🔖 Ваше избранное: {favs_n}\n\n"
        f"<i>По боту в целом:</i>\n"
        f"• Активных подписчиков: {len(db.active_users())}\n"
        f"• Лотов в истории: {db.seen_count()}\n"
        f"• Проверка сайта каждые {config.MONITOR_INTERVAL_MINUTES} мин"
    )
    await msg.answer(text, parse_mode="HTML")


@router.message(Command("test"))
async def cmd_test(msg: Message) -> None:
    """Прислать самый свежий лот с сайта — для проверки рендеринга."""
    await msg.answer("Ищу свежий лот…")
    try:
        item = await asyncio.to_thread(_fetch_latest)
    except Exception as e:
        logger.warning("test: ошибка: %s", e)
        logger.debug("traceback:", exc_info=True)
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
