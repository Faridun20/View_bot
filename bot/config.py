"""Конфигурация бота — читается из переменных окружения или .env."""
from __future__ import annotations

import os
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


# Telegram
TG_BOT_TOKEN: str | None = _env("TG_BOT_TOKEN")
ADMIN_IDS: list[int] = [
    int(x) for x in _env("ADMIN_IDS", "").split(",") if x.strip().isdigit()
]

# Пути (Railway: /data — это volume mount, локально — ./data)
DATA_DIR = Path(_env("DATA_DIR", "data"))
DATA_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = DATA_DIR / "bot.db"

# Парсер: storage_state.json от Playwright (cookie CUPID).
# Кладём в DATA_DIR, чтобы пережил рестарт контейнера.
CUPID_STORAGE = DATA_DIR / "storage_state.json"

# Расписание мониторинга
MONITOR_INTERVAL_MINUTES = int(_env("MONITOR_INTERVAL_MINUTES", "60") or 60)

# DEPRECATED: раньше был жёсткий лимит на сообщения в одном scan'е, но он
# приводил к ПОТЕРЕ лотов (они оказывались помечены seen без рассылки).
# Защита от первичного потопа теперь полностью на SEED_RECENT_LOTS.
MAX_NOTIFICATIONS_PER_RUN = int(_env("MAX_NOTIFICATIONS_PER_RUN", "0") or 0)  # 0 = не использовать

# Сколько дней хранить записи в таблице sent. После — авто-cleanup.
# seen_pids чистить нельзя, иначе старые лоты вернутся в поток.
SENT_RETENTION_DAYS = int(_env("SENT_RETENTION_DAYS", "90") or 90)

# Сколько ранее виденных лотов перепроверять на каждом scan'е — для
# отслеживания снижений цены. ~30 даёт хорошее покрытие свежих, не
# съедая много времени scan'а (30 * 0.5 сек = 15 сек).
PRICE_CHECK_TOP_N = int(_env("PRICE_CHECK_TOP_N", "30") or 30)

# Healthcheck-сервер (для Railway). Если переменная PORT задана — поднимаем
# минимальный HTTP-сервер на /health (он не блокирует polling-бота).
HEALTHCHECK_PORT = int(_env("PORT", "0") or _env("HEALTHCHECK_PORT", "0") or 0)

# Telegram ID администраторов через запятую — могут /users и /broadcast.
# Пример: ADMIN_IDS=123456789,987654321

# Сколько лотов из истории «зачесть как уже виденные» при первом запуске,
# чтобы не спамить старыми объявлениями.
SEED_RECENT_LOTS = int(_env("SEED_RECENT_LOTS", "200") or 200)

# Включать ли в мониторинг подкатегории «навесное оборудование» (어태치먼트)
# и «запчасти для экскаваторов» (굴삭기부속). По умолчанию выключено —
# в /search и почасовом обходе только сама техника.
INCLUDE_PARTS: bool = (_env("INCLUDE_PARTS", "false") or "false").strip().lower() in ("1", "true", "yes")

# Логирование
LOG_LEVEL = _env("LOG_LEVEL", "INFO")
