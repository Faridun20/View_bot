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

# Сколько новых лотов за один прогон макс. отправляем одному юзеру (защита
# от спама при первом запуске — иначе сразу ливанёт сотни сообщений).
MAX_NOTIFICATIONS_PER_RUN = int(_env("MAX_NOTIFICATIONS_PER_RUN", "20") or 20)

# Сколько лотов из истории «зачесть как уже виденные» при первом запуске,
# чтобы не спамить старыми объявлениями.
SEED_RECENT_LOTS = int(_env("SEED_RECENT_LOTS", "200") or 200)

# Включать ли в мониторинг подкатегории «навесное оборудование» (어태치먼트)
# и «запчасти для экскаваторов» (굴삭기부속). По умолчанию выключено —
# в /search и почасовом обходе только сама техника.
INCLUDE_PARTS: bool = (_env("INCLUDE_PARTS", "false") or "false").strip().lower() in ("1", "true", "yes")

# Логирование
LOG_LEVEL = _env("LOG_LEVEL", "INFO")
