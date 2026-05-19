"""Точка входа: запускает aiogram-бота и APScheduler с почасовым мониторингом."""
from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from bot import config
from bot.handlers import build_root_router
from bot.healthcheck import start_healthcheck
from bot.monitor import run_scan, seed_seen
from bot.scraper.client import CupidSession
from bot.storage import init_db


async def main() -> None:
    logging.basicConfig(
        level=config.LOG_LEVEL,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    log = logging.getLogger("bot.main")

    if not config.TG_BOT_TOKEN:
        raise SystemExit(
            "TG_BOT_TOKEN не задан. Получите токен у @BotFather и положите в .env "
            "или env-переменную."
        )

    # Принудительно настраиваем парсер на использование пути из конфига
    # (а не дефолтного recon_out/storage_state.json). Создание сессии
    # уходит в поток: при первом запуске без cookie оно запускает
    # sync_playwright, а sync API нельзя вызывать из активного asyncio loop.
    import bot.scraper.client as client_mod
    client_mod._singleton = await asyncio.to_thread(
        CupidSession, config.CUPID_STORAGE
    )

    db = init_db(config.DB_PATH)

    bot = Bot(
        token=config.TG_BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(build_root_router())

    # При первом запуске «зачесть» последние N лотов как виденные,
    # чтобы не утопить подписчиков в сотнях старых объявлений.
    log.info("Прогрев: seed_seen(take=%d)", config.SEED_RECENT_LOTS)
    await seed_seen(db, take=config.SEED_RECENT_LOTS)

    scheduler = AsyncIOScheduler(timezone="UTC")
    scheduler.add_job(
        run_scan, IntervalTrigger(minutes=config.MONITOR_INTERVAL_MINUTES),
        kwargs={"bot": bot, "db": db}, id="scan",
        next_run_time=None,             # первый запуск через interval, не сразу
        max_instances=1, coalesce=True,
    )

    # Раз в сутки чистим старые sent — sent растёт линейно от трафика,
    # после 90 дней эти записи не имеют смысла (юзер не помнит лот).
    async def _cleanup() -> None:
        removed = await asyncio.to_thread(db.cleanup_old_sent, config.SENT_RETENTION_DAYS)
        log.info("cleanup_old_sent: удалено %d записей старше %d дней",
                 removed, config.SENT_RETENTION_DAYS)

    scheduler.add_job(_cleanup, IntervalTrigger(hours=24), id="cleanup",
                      max_instances=1, coalesce=True)

    scheduler.start()
    log.info("Планировщик запущен: scan каждые %d мин, cleanup каждые 24ч",
             config.MONITOR_INTERVAL_MINUTES)

    # Healthcheck: только если задан HEALTHCHECK_PORT/PORT (например, на Railway).
    health_runner = await start_healthcheck(db, config.HEALTHCHECK_PORT)

    log.info("Стартую long-polling")
    try:
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        scheduler.shutdown(wait=False)
        if health_runner is not None:
            await health_runner.cleanup()
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
