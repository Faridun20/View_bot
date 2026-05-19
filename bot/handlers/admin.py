"""Команды только для администраторов из ADMIN_IDS.

/users — список подписчиков с их фильтрами
/broadcast <текст> — массовое сообщение всем активным
/stats — расширенная статистика
"""
from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import Command, CommandObject
from aiogram.types import Message

from bot import config
from bot.handlers.filters import _describe as describe_filter
from bot.storage import init_db

logger = logging.getLogger(__name__)
router = Router(name="admin")


def _is_admin(msg: Message) -> bool:
    """True если юзер указан в env ADMIN_IDS ИЛИ имеет флаг is_admin в БД
    (auto-admin для первого подписчика, см. db.upsert_user)."""
    if not msg.from_user:
        return False
    uid = msg.from_user.id
    if uid in set(config.ADMIN_IDS):
        return True
    try:
        return init_db(config.DB_PATH).is_admin(uid)
    except Exception:
        return False


@router.message(Command("users"))
async def cmd_users(msg: Message) -> None:
    if not _is_admin(msg):
        return  # тихо игнорируем для не-админов
    db = init_db(config.DB_PATH)
    actives = db.active_users()
    lines = [f"<b>Подписчиков активных:</b> {len(actives)}"]
    for u in actives[:30]:                       # покажем максимум 30
        f = db.get_filter(u)
        descr = describe_filter(f).replace("\n", " | ") if not f.is_empty() else "—"
        lines.append(f"\n👤 <code>{u}</code>\n{descr}")
    if len(actives) > 30:
        lines.append(f"\n…и ещё {len(actives) - 30}")
    await msg.answer("\n".join(lines), parse_mode="HTML")


@router.message(Command("broadcast"))
async def cmd_broadcast(msg: Message, command: CommandObject) -> None:
    if not _is_admin(msg):
        return
    text = (command.args or "").strip()
    if not text:
        await msg.answer(
            "Использование: <code>/broadcast Текст сообщения</code>\n"
            "Поддерживается HTML.",
            parse_mode="HTML",
        )
        return
    db = init_db(config.DB_PATH)
    actives = db.active_users()
    await msg.answer(f"Рассылаю на {len(actives)} активных…")
    ok, fail = 0, 0
    for chat_id in actives:
        try:
            await msg.bot.send_message(chat_id, text, parse_mode="HTML")
            ok += 1
            await asyncio.sleep(0.05)            # rate-limit
        except TelegramAPIError as e:
            logger.warning("broadcast: чат %s — %s", chat_id, e)
            fail += 1
    await msg.answer(f"Готово: ✅ {ok}, ❌ {fail}")


@router.message(Command("stats"))
async def cmd_stats(msg: Message) -> None:
    if not _is_admin(msg):
        return
    db = init_db(config.DB_PATH)
    actives = db.active_users()
    text = (
        "<b>📊 Статистика</b>\n\n"
        f"• Активных подписчиков: <b>{len(actives)}</b>\n"
        f"• Лотов в истории (seen_pids): <b>{db.seen_count()}</b>\n"
        f"• Интервал проверки: {config.MONITOR_INTERVAL_MINUTES} мин\n"
        f"• INCLUDE_PARTS: {config.INCLUDE_PARTS}\n"
        f"• ADMIN_IDS: {len(config.ADMIN_IDS)} админов\n"
    )
    await msg.answer(text, parse_mode="HTML")


@router.message(Command("scan_now"))
async def cmd_scan_now(msg: Message) -> None:
    """Форсировать запуск почасового сканирования прямо сейчас."""
    if not _is_admin(msg):
        return
    await msg.answer("🚀 Запускаю принудительный scan…")
    # Импорт здесь — чтобы не плодить циклы (monitor → notifier → db → ...)
    from bot.monitor import run_scan
    db = init_db(config.DB_PATH)
    try:
        await run_scan(msg.bot, db)
        await msg.answer("✅ Scan завершён. Если ничего не пришло — значит "
                         "новых лотов в каталоге не появилось (или фильтр у "
                         "юзеров не совпал).")
    except Exception as e:
        logger.exception("scan_now failed")
        await msg.answer(f"❌ Ошибка: <code>{e}</code>", parse_mode="HTML")
