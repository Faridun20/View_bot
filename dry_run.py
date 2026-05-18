"""Сухой запуск без Telegram-токена.

Проверяет:
1. Импорты всех модулей (синтаксические ошибки видны сразу).
2. БД создаётся, фильтр сохраняется и читается.
3. Логика matches() — на синтетических примерах.
4. Полный цикл monitor._scan_categories() + парс одной свежей карточки.
5. Форматирование notifier.format_listing().
"""
from __future__ import annotations

import logging
import os
from pathlib import Path

# До любого импорта config — переопределим путь к БД и storage_state,
# чтобы не мешать боевым данным.
os.environ.setdefault("DATA_DIR", "dry_run_data")

from bot import config, monitor, notifier  # noqa: E402
from bot.monitor import _fetch_item, _scan_categories, matches  # noqa: E402
from bot.scraper.client import CupidSession  # noqa: E402
import bot.scraper.client as client_mod  # noqa: E402
from bot.scraper.models import Listing  # noqa: E402
from bot.storage import init_db  # noqa: E402
from bot.storage.db import UserFilter  # noqa: E402


def header(t: str) -> None:
    print("\n" + "=" * 70)
    print(f"  {t}")
    print("=" * 70)


def main() -> int:
    logging.basicConfig(level="INFO", format="%(levelname)s %(name)s: %(message)s")

    # Заюзаем уже прогретый storage_state.json из recon_out — не тратим время
    # на ещё один Playwright-запуск.
    seed = Path("recon_out/storage_state.json")
    if seed.exists():
        config.CUPID_STORAGE.parent.mkdir(parents=True, exist_ok=True)
        config.CUPID_STORAGE.write_bytes(seed.read_bytes())
        print(f"Скопировал cookie из {seed} в {config.CUPID_STORAGE}")
    client_mod._singleton = CupidSession(storage_path=config.CUPID_STORAGE)

    # --- 1. БД ----------------------------------------------------------
    header("1. БАЗА ДАННЫХ")
    db_path = config.DB_PATH
    if db_path.exists():
        db_path.unlink()
    db = init_db(db_path)
    print(f"  БД создана: {db_path}")

    db.upsert_user(12345, "alice")
    db.upsert_user(67890, "bob")
    print(f"  Активных пользователей: {len(db.active_users())}")
    assert db.active_users() == [12345, 67890]

    # Сохраняем фильтр Alice — Volvo, 2018+, до 10000 万원
    f1 = UserFilter(chat_id=12345, manufacturer="볼보",
                    year_from=2018, price_max_won=10000 * 10_000)
    db.set_filter(f1)
    got = db.get_filter(12345)
    assert got.manufacturer == "볼보"
    assert got.price_max_won == 100_000_000
    print(f"  Фильтр Alice сохранён/прочитан: ✓")

    # Bob без фильтра
    bob = db.get_filter(67890)
    assert bob.is_empty()
    print(f"  У Bob фильтр пустой: ✓")

    # seen_pids / sent
    assert db.mark_seen(111, "100100") is True
    assert db.mark_seen(111, "100100") is False     # дубль
    assert db.is_seen(111)
    assert not db.is_seen(222)
    db.mark_sent(12345, 111)
    assert db.was_sent(12345, 111)
    assert not db.was_sent(67890, 111)
    print("  seen_pids и sent: ✓")

    # --- 2. matches() ---------------------------------------------------
    header("2. ЛОГИКА ФИЛЬТРОВ")

    volvo_old = Listing(
        pid=1, url="x", manufacturer="볼보", year="2015.03",
        price_won=80_000_000, hours=8000, model="380D",
        description="튼튼한 차량",
    )
    volvo_new = Listing(
        pid=2, url="x", manufacturer="볼보", year="2020.07",
        price_won=80_000_000, hours=5000, model="EC480",
        description="",
    )
    hyundai = Listing(
        pid=3, url="x", manufacturer="현대", year="2021.01",
        price_won=60_000_000, hours=3000, model="HX380",
    )

    # Alice: Volvo, 2018+, до 100 млн ВОН
    print("  Alice (Volvo / 2018+ / ≤100 млн):")
    print(f"    volvo_old (2015): match = {matches(volvo_old, f1)} (ожидаю False)")
    print(f"    volvo_new (2020): match = {matches(volvo_new, f1)} (ожидаю True)")
    print(f"    hyundai:          match = {matches(hyundai, f1)} (ожидаю False)")
    assert not matches(volvo_old, f1)
    assert matches(volvo_new, f1)
    assert not matches(hyundai, f1)

    # Bob (пустой) — пускает всё
    print("  Bob (без фильтра): пропускает всё:")
    assert all(matches(l, bob) for l in [volvo_old, volvo_new, hyundai])
    print("    ✓")

    # Ключевое слово
    f_kw = UserFilter(chat_id=999, keyword="380")
    print(f"  keyword='380' — volvo_old: {matches(volvo_old, f_kw)}, hyundai: {matches(hyundai, f_kw)}")
    assert matches(volvo_old, f_kw)
    assert matches(hyundai, f_kw)
    assert not matches(volvo_new, f_kw)

    # Лот без года при выставленном фильтре по году — отсекаем
    no_year = Listing(pid=4, url="x", manufacturer="볼보", year=None,
                      price_won=50_000_000)
    assert not matches(no_year, f1)
    print(f"  Лот без года при year_from=2018: matches = False ✓")

    # --- 3. Живой scan --------------------------------------------------
    header("3. ЖИВОЙ ОБХОД САЙТА")
    found = _scan_categories()
    print(f"  Найдено лотов: {len(found)}")
    assert len(found) > 100, "обход вернул подозрительно мало лотов"
    top_pid = max(found.keys())
    print(f"  Топ-pid: {top_pid}")

    # --- 4. Карточка ----------------------------------------------------
    header("4. ПАРСИНГ КАРТОЧКИ ТОП-ЛОТА")
    item = _fetch_item(top_pid)
    assert item is not None
    print(f"  pid={item.pid}")
    print(f"  model={item.model}")
    print(f"  manufacturer={item.manufacturer}")
    print(f"  year={item.year}  → year_int={None if not item.year else item.year[:4]}")
    print(f"  price_raw={item.price_raw}  → price_won={item.price_won}")
    print(f"  hours_raw={item.hours_raw!r}  → hours={item.hours}")
    print(f"  region={item.region}")
    print(f"  posted_at={item.posted_at}")
    print(f"  photos={len(item.photos)}")

    # --- 5. Форматирование карточки ------------------------------------
    header("5. ОТРИСОВКА В TELEGRAM-ФОРМАТЕ")
    text = notifier.format_listing(item)
    print(text)
    print()
    print(f"  Длина: {len(text)} символов (лимит caption = 1024)")

    header("ВСЁ ЗЕЛЁНОЕ")
    print("  Бот готов к запуску. Дальше — выставить TG_BOT_TOKEN и `python -m bot.main`.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
