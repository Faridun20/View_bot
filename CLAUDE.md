# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

Telegram-бот (aiogram 3.x + APScheduler) для мониторинга корейского сайта
подержанной строительной техники **4396200.com** (그린중기, категория «Экскаваторы»).
Бот раз в час обходит 6 подкатегорий машин, парсит карточки, фильтрует
по настройкам каждого подписчика и шлёт совпадения в Telegram. Также
поддерживает ad-hoc `/search`, избранное, и уведомления о снижении цены.

## Common commands

```bash
# первое включение
python -m venv .venv
.venv/Scripts/activate            # Windows
# source .venv/bin/activate       # macOS / Linux
pip install -r requirements-dev.txt
python -m playwright install chromium     # ~150 МБ, нужно один раз

# запуск (нужен TG_BOT_TOKEN в .env)
python -m bot.main

# тесты — 93 теста, ~10 секунд, без обращения к сайту
pytest tests/ -q
pytest tests/test_filters.py::test_filter_by_region -v   # один тест
pytest tests/ -q -k "price"                              # по подстроке

# разведочные скрипты (не нужны в обычной работе, оставлены для отладки)
python recon.py        # сохраняет HTML главной + ссылки в recon_out/
python recon2.py       # докачивает категории/карточки
python scrape_test.py  # живой тест парсера на сайте
python dry_run.py      # сухой прогон без TG-токена
```

## Architecture (big picture)

Слои, каждый зависит только от нижестоящих:

```
handlers/  (aiogram routers — команды, callbacks, FSM)
   │
notifier   (формирование карточки → send_photo / send_message)
   │
monitor    (run_scan: scan_categories → fetch_item → matches → send)
search     (ad-hoc вариант run_scan с прогрессом и превью-фильтрами)
   │
catalog    (единый сервисный слой обхода сайта: scan_previews /
            scan_categories / fetch_item / fetch_latest — sync, в to_thread)
   │
storage/db (SQLite через sqlite3, WAL, миграция в _migrate())
scraper/   (cupid → client → parser → models — четырёхслойный парсер)
config     (типизированный Settings.from_env() + модульные алиасы-константы)
```

**`bot/catalog.py`** — единственная точка обхода каталога. Раньше эта
логика дублировалась в `monitor._scan_categories` и
`search._scan_with_previews`; теперь обе ходят через `catalog`. В `monitor`
оставлены тонкие алиасы `_scan_categories`/`_fetch_item → catalog.*` для
обратной совместимости (на них ещё ссылаются тесты). Новый код должен
импортировать из `bot.catalog` напрямую.

**`config`** — источник правды это `@dataclass Settings`; `config.settings`
— готовый инстанс из окружения. Модульные константы (`config.DB_PATH` и т.п.)
оставлены алиасами полей `settings` для обратной совместимости и для
тестовой фикстуры `isolated_db`, которая перезагружает модуль.

### Парсер (`bot/scraper/`)

`cupid.py` → `client.py` → `parser.py` → `models.py`:

- **`cupid.py`** обходит самописный JS-челлендж сайта (slowAES + cookie `CUPID`).
  Использует **sync** Playwright, поэтому в asyncio-приложении вызывается
  ИСКЛЮЧИТЕЛЬНО через `asyncio.to_thread`. Иначе падает с
  «Playwright Sync API inside the asyncio loop».
- **`client.py`** — `CupidSession` (requests.Session с подгруженной cookie).
  При получении заглушки Cupid (детектится по `/cupid.js`, `slowAES`, `CUPID=` в первых 5 КБ
  ответа) автоматически рефрешит cookie через `cupid.refresh_cupid_cookie`.
  Сервер не присылает `charset`, поэтому `resp.encoding="utf-8"` ставится принудительно.
- **`parser.py`** — BeautifulSoup на lxml. Две точки входа:
  `parse_listing_page` (страница списка → `ListingPreview[]`) и
  `parse_item_page` (карточка → `Listing`). Цены парсятся
  во всех корейских форматах: `만원`, `억`, `천만` и их комбинации
  (например `1억3천만원` = 130 млн ВОН).
- **`models.py`** — dataclass'ы `Listing`/`ListingPreview` + утилиты
  (`grade_rank`, `normalize_region`, `region_matches`, `target_subcategories`,
  `looks_like_parts`).

### Хранилище (`bot/storage/db.py`)

SQLite через стандартный `sqlite3` (sync), вызывается из async кода через
`asyncio.to_thread`. WAL включается в `_init()`. Миграция — **ALTER TABLE
в `_migrate()`**, не Alembic. **Когда добавляете новую колонку в схему — ОБЯЗАТЕЛЬНО
добавьте её и в список `adders` в `_migrate()`, иначе старые деплои на
Railway упадут.**

Таблицы: `users`, `filters`, `seen_pids`, `sent`, `favorites`, `price_history`.

### Цикл мониторинга (`bot/monitor.py`)

`run_scan` — единственная точка входа для APScheduler:

1. `_scan_categories()` обходит подкатегории, собирает `{pid: cate_code}`.
2. Берёт pid, которых нет в `seen_pids`. Для каждого парсит карточку.
   **Canary**: если все основные поля карточки `None` — парсер сломан под изменения
   сайта, помечаем seen и не шлём «— · — · —».
3. Для каждого подписчика проверяет `matches(item, filter)` и шлёт.
   Помечает `seen_pids` + `sent`.
4. `_check_price_drops()` дополнительно перепроверяет последние
   `PRICE_CHECK_TOP_N` (default 30) уже виденных лотов. При **снижении**
   цены — шлёт уведомление через `notifier.send_price_drop` всем
   `recipients_for_price_drop(pid)` = `sent` ∪ `favorites`.

### UI (handlers)

Три параллельных способа взаимодействия (один роутер на каждый — порядок
важен, см. `handlers/__init__.py::build_root_router`):

| Способ | Роутер | Примеры |
|---|---|---|
| Текстовые команды | `start.py`, `filters.py`, `search.py`, `favorites.py`, `admin.py` | `/start`, `/search 10`, `/favs` |
| Inline-меню | `menu.py` + `keyboards.py` | `/menu` → drill-down кнопками |
| FSM-ввод | `filters.py` (старый /filter), `menu.py::MenuInput` (Своё значение в меню) | Цена, моточасы, ключевое слово |

**Callback data ограничена 64 байтами Telegram'ом.** Используются короткие
префиксы: `m:` (main menu), `s:` (search), `f:` / `fm:` / `fs:` / `fr:` /
`fg:` / `fp:` / `fh:` / `fk:` / `fb:` / `fph:` / `fnoh:` / `fyf:` / `fyt:`
(filter edit), `fav:`, `bl:`.

В FSM-handlers всегда используется фильтр `~F.text.startswith("/")` — иначе
команда `/menu` посреди ввода числа улетит в text-handler как «не число».
Универсальный `/cancel` выходит из любого активного состояния.

### Auto-admin

`db.upsert_user()` ставит `is_admin=1` если в БД ещё **никого** не было —
первый юзер автоматически становится админом, ничего настраивать не нужно.
`_is_admin()` в `handlers/admin.py` проверяет ОБА источника: env
`ADMIN_IDS` И флаг в БД.

## Quirks worth remembering

- **Sync ↔ async boundary.** Парсер, Playwright и SQLite — все sync.
  Из `async def` вызываются через `asyncio.to_thread(...)`, иначе либо
  блокируем event loop, либо падает sync_playwright. Никогда не вызывайте
  `CupidSession(...)` напрямую из async-контекста при отсутствии
  cookie-файла — это вызовет `refresh_cupid_cookie` внутри loop'а.

- **Корейский язык в БД.** Производители (`볼보`), регионы (`강원`),
  подкатегории (`어태치먼트`), грейды (`A+급`) хранятся **as-is** — все
  сравнения строкой. Утилиты `normalize_region` и `looks_like_parts` —
  единственные места, где есть знание корейского.

- **PARTS-фильтр работает на двух уровнях.** Подкатегории 100106/100107
  (`어태치먼트`/`굴삭기부속`) исключаются ещё на этапе `target_subcategories()`.
  Дополнительно `matches()` отсекает по `looks_like_parts(category_path)` —
  для случая, когда лот «просочился» в правильную подкатегорию.
  `looks_like_parts` проверяет ТОЛЬКО листовой сегмент пути после `>`,
  потому что родительская группа `굴삭기/어태치부속` содержит `어태치` у
  ВСЕХ 8 подкатегорий.

- **`seen_pids` vs `sent`.** `seen_pids` — глобальный список «бот когда-либо
  обрабатывал этот pid» (для дедупликации почасового обхода). `sent` —
  per-user «отправили этот pid в этот чат» (для повторов через `/search`
  и `/forget`). НЕ путать.

- **`PID` инкрементный** — самая свежая публикация имеет максимальный
  `pid`. Это используется и в seed (берём топ-N как «уже виденные» при
  первом старте), и в сортировке `/search`.

- **Версии Playwright должны совпадать.** В `Dockerfile` тег образа
  `mcr.microsoft.com/playwright/python:v<X>-jammy` и `playwright==<X>` в
  `requirements.txt` должны быть одной и той же версии. При апгрейде —
  ОБЕ строки одновременно.

## Deployment

Railway + Docker. Volume на `/data` обязателен — иначе SQLite (а с ней
история отправлений) теряется при каждом редеплое. Подробности в `README.md`.

CI: `.github/workflows/ci.yml` запускает pytest на push/PR в main для
Python 3.11 и 3.12. На CI Chromium НЕ ставится — тесты не ходят в сайт,
работают с фикстурами в `tests/fixtures/` (3 HTML-снапшота, ~800 КБ).
