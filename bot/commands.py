"""Регистрация команд бота (для меню `/` в Telegram-клиенте) и кнопки Menu.

Вызывается один раз при старте из bot.main.
"""
from __future__ import annotations

import logging

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from aiogram.types import (
    BotCommand,
    BotCommandScopeChat,
    BotCommandScopeDefault,
    MenuButtonCommands,
)

from bot import config
from bot.storage import init_db

logger = logging.getLogger(__name__)


# Команды, видимые всем пользователям при наборе «/».
USER_COMMANDS = [
    BotCommand(command="menu",     description="Главное меню"),
    BotCommand(command="search",   description="Свежие лоты по фильтру"),
    BotCommand(command="filter",   description="Настроить фильтр"),
    BotCommand(command="myfilter", description="Показать текущий фильтр"),
    BotCommand(command="favs",     description="Избранные лоты"),
    BotCommand(command="history",  description="История цен лота (по pid)"),
    BotCommand(command="forget",   description="Очистить историю показанных"),
    BotCommand(command="status",   description="Статистика бота"),
    BotCommand(command="help",     description="Справка"),
]

# Дополнительные команды для админов (видны только им).
ADMIN_COMMANDS = USER_COMMANDS + [
    BotCommand(command="scan_now",  description="🚀 Запустить scan сейчас"),
    BotCommand(command="stats",     description="📊 Расширенная статистика"),
    BotCommand(command="users",     description="👥 Список подписчиков"),
    BotCommand(command="broadcast", description="📣 Рассылка всем"),
]


async def setup_bot_commands(bot: Bot) -> None:
    """Установить /commands в Telegram и кнопку Menu рядом с полем ввода.

    Кнопка Menu (через set_chat_menu_button) — глобально для всех, она
    раскрывает список команд (это эквивалентно типу MenuButtonCommands).
    """
    try:
        # Глобальные команды для всех юзеров
        await bot.set_my_commands(USER_COMMANDS, scope=BotCommandScopeDefault())

        # Точечные команды для каждого админа из БД (auto-admin + ADMIN_IDS).
        # Telegram-клиент покажет ИМ расширенный список.
        admin_ids: set[int] = set(config.ADMIN_IDS)
        try:
            admin_ids |= set(init_db(config.DB_PATH).list_admins())
        except Exception:
            logger.debug("setup_bot_commands: не удалось прочитать list_admins", exc_info=True)

        for chat_id in admin_ids:
            try:
                await bot.set_my_commands(
                    ADMIN_COMMANDS,
                    scope=BotCommandScopeChat(chat_id=chat_id),
                )
            except TelegramAPIError as e:
                # Если админ ещё не писал боту — set_my_commands упадёт.
                # Это не страшно: команды появятся после первого /start.
                logger.debug("Не смог установить admin-команды для %s: %s", chat_id, e)

        # Кнопка Menu для всех чатов (рядом с полем ввода)
        await bot.set_chat_menu_button(menu_button=MenuButtonCommands())
        logger.info("setup_bot_commands: установлено %d user-команд, "
                    "+%d admin-команд для %d админов",
                    len(USER_COMMANDS),
                    len(ADMIN_COMMANDS) - len(USER_COMMANDS),
                    len(admin_ids))
    except TelegramAPIError as e:
        logger.warning("setup_bot_commands failed: %s", e)
