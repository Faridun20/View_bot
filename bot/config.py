"""Конфигурация бота.

Единый источник правды — типизированный :class:`Settings`, собираемый из
переменных окружения / .env. Для обратной совместимости (и чтобы тестовая
фикстура `isolated_db`, перезагружающая модуль, продолжала работать) ниже
оставлены модульные алиасы вида ``DB_PATH = settings.db_path`` — они
пересчитываются при каждом reload модуля.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

try:
    from dotenv import load_dotenv

    # Загружаем .env, если он лежит рядом (для локальной разработки).
    load_dotenv()
except ImportError:
    pass


def _env(name: str, default: str | None = None, *, required: bool = False) -> str | None:
    v = os.getenv(name, default)
    if required and not v:
        raise RuntimeError(f"env-переменная {name} обязательна")
    return v


def _int(name: str, default: int) -> int:
    """int из env с устойчивостью к пустой строке/мусору."""
    raw = _env(name, str(default))
    try:
        return int(raw) if raw and raw.strip() else default
    except ValueError:
        return default


def _bool(name: str, default: bool) -> bool:
    raw = (_env(name, str(default)) or "").strip().lower()
    return raw in ("1", "true", "yes", "on")


def _admin_ids(raw: str | None) -> list[int]:
    return [int(x) for x in (raw or "").split(",") if x.strip().isdigit()]


@dataclass(frozen=True)
class Settings:
    """Все параметры бота. Создаётся из окружения через :meth:`from_env`,
    но может конструироваться напрямую — это упрощает тесты."""

    # Telegram
    tg_bot_token: str | None = None
    admin_ids: list[int] = field(default_factory=list)

    # Пути (Railway: /data — volume mount, локально — ./data)
    data_dir: Path = Path("data")
    db_path: Path = Path("data/bot.db")
    cupid_storage: Path = Path("data/storage_state.json")

    # Расписание / мониторинг
    monitor_interval_minutes: int = 60
    sent_retention_days: int = 90
    price_check_top_n: int = 30
    seed_recent_lots: int = 200

    # Прочее
    healthcheck_port: int = 0
    include_parts: bool = False
    log_level: str = "INFO"

    @classmethod
    def from_env(cls) -> "Settings":
        data_dir = Path(_env("DATA_DIR", "data") or "data")
        data_dir.mkdir(parents=True, exist_ok=True)
        return cls(
            tg_bot_token=_env("TG_BOT_TOKEN"),
            admin_ids=_admin_ids(_env("ADMIN_IDS", "")),
            data_dir=data_dir,
            db_path=data_dir / "bot.db",
            # storage_state.json от Playwright (cookie CUPID) — в DATA_DIR,
            # чтобы пережил рестарт контейнера.
            cupid_storage=data_dir / "storage_state.json",
            monitor_interval_minutes=_int("MONITOR_INTERVAL_MINUTES", 60),
            sent_retention_days=_int("SENT_RETENTION_DAYS", 90),
            # Сколько ранее виденных лотов перепроверять на снижение цены
            # за один scan. ~30 — хорошее покрытие свежих без долгого scan'а.
            price_check_top_n=_int("PRICE_CHECK_TOP_N", 30),
            # Сколько лотов «зачесть как виденные» при первом запуске, чтобы
            # не спамить старыми объявлениями.
            seed_recent_lots=_int("SEED_RECENT_LOTS", 200),
            # Healthcheck-сервер (Railway): если PORT задан — поднимаем /health.
            healthcheck_port=_int("PORT", 0) or _int("HEALTHCHECK_PORT", 0),
            # Включать ли навесное (어태치먼트) и запчасти (굴삭기부속).
            include_parts=_bool("INCLUDE_PARTS", False),
            log_level=_env("LOG_LEVEL", "INFO") or "INFO",
        )


settings = Settings.from_env()


# --------------------------------------------------------------------------
# Обратная совместимость: модульные константы как алиасы полей settings.
# Существующий код обращается к `config.DB_PATH` и т.п. При reload модуля
# (тестовая фикстура) пересчитываются автоматически.
# --------------------------------------------------------------------------
TG_BOT_TOKEN = settings.tg_bot_token
ADMIN_IDS = settings.admin_ids
DATA_DIR = settings.data_dir
DB_PATH = settings.db_path
CUPID_STORAGE = settings.cupid_storage
MONITOR_INTERVAL_MINUTES = settings.monitor_interval_minutes
SENT_RETENTION_DAYS = settings.sent_retention_days
PRICE_CHECK_TOP_N = settings.price_check_top_n
SEED_RECENT_LOTS = settings.seed_recent_lots
HEALTHCHECK_PORT = settings.healthcheck_port
INCLUDE_PARTS = settings.include_parts
LOG_LEVEL = settings.log_level

# DEPRECATED: жёсткий лимит сообщений за scan приводил к ПОТЕРЕ лотов
# (помечались seen без рассылки). Защита теперь полностью на SEED_RECENT_LOTS.
MAX_NOTIFICATIONS_PER_RUN = 0
