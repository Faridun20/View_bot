# Telegram-бот мониторинга 4396200.com (그린중기)

Следит за новыми объявлениями в категории **«Экскаваторы»** на корейском
сайте подержанной строительной техники [4396200.com](https://www.4396200.com)
и присылает подписчикам карточки с фото и фильтрами:

- производитель (Volvo / Hyundai / Doosan / Caterpillar / …)
- год выпуска (от и до)
- максимальная цена (в 만원 = 10 000 ВОН)
- максимальные моточасы
- ключевое слово в названии/описании

Лоты без указанных моточасов помечаются «не указаны» и всё равно приходят.

---

## Команды бота

| Команда | Что делает |
|---------|-----------|
| `/start` | Подписаться |
| `/stop`  | Отписаться |
| `/filter` | Пошагово настроить фильтр |
| `/myfilter` | Показать текущий фильтр |
| `/reset` | Сбросить фильтр — приходят все новые лоты |
| `/test` | Прислать самый свежий лот (проверить, что бот работает) |
| `/status` | Статистика: число подписчиков, размер истории |
| `/help`  | Справка |

---

## Архитектура

```
bot/
├── scraper/         парсинг сайта (Playwright обновляет cookie CUPID раз в сутки;
│                    дальше — обычный requests + BeautifulSoup)
├── storage/         SQLite (users / filters / seen_pids / sent)
├── handlers/        aiogram-роутеры команд
├── notifier.py      форматирование карточки + send_photo/send_message
├── monitor.py       APScheduler-задача: ежечасный обход 8 подкатегорий
└── main.py          точка входа: dispatcher + scheduler
```

Защита сайта (самописный JS-челлендж «Cupid») обходится Playwright'ом
один раз в сутки — cookie сохраняется на volume и переиспользуется обычным
`requests`. Браузер не висит в памяти постоянно.

---

## Локальный запуск (Windows / macOS / Linux)

```bash
python -m venv .venv
.\.venv\Scripts\activate            # Windows
# source .venv/bin/activate         # macOS / Linux

pip install -r requirements.txt
playwright install chromium

cp .env.example .env                # macOS / Linux
# copy .env.example .env            # Windows
# затем впишите TG_BOT_TOKEN

python -m bot.main
```

При первом запуске Playwright скачает Chromium (~150 МБ).

---

## Деплой на Railway

### 1. Один раз: создать бота

1. Открыть [@BotFather](https://t.me/BotFather) → `/newbot` → задать имя.
2. Сохранить токен вида `1234567890:ABC-…`.

### 2. Залить код на GitHub

```bash
git init
git add .
git commit -m "Initial bot"
git remote add origin https://github.com/Faridun20/View_bot.git
git branch -M main
git push -u origin main
```

### 3. Railway

1. [railway.app](https://railway.app) → **New Project** → **Deploy from GitHub repo** →
   выбрать `Faridun20/View_bot`.
2. Railway сам найдёт `Dockerfile` и начнёт сборку (~3 минуты).
3. **Variables** → добавить:
   - `TG_BOT_TOKEN` = токен от BotFather
   - (опционально) `ADMIN_IDS` = ваш Telegram ID
4. **Settings → Volumes** → **Mount path `/data`** → размер 1 GB.
   Это критично: иначе при каждом деплое история отправленных лотов
   потеряется и бот заспамит подписчиков повторами.
5. **Settings → Region** → выбрать **Singapore** или **Frankfurt** (ближе к Корее).

После первого деплоя бот:
- разок прогреет cookie CUPID (~20 сек);
- «зачтёт» последние 200 лотов как уже виденные (`SEED_RECENT_LOTS`);
- начнёт обходить сайт каждый `MONITOR_INTERVAL_MINUTES` (по умолчанию 60).

### 4. Расход ресурсов

| Ресурс | Расход | Hobby Plan лимит |
|--------|-------|-----------------|
| RAM | ~200 МБ | 8 GB |
| CPU | ~0.05 vCPU avg | 8 vCPU |
| Сеть | ~5 МБ/час | — |
| Диск | ~1.2 ГБ образ + ~5 МБ БД | 5 GB |
| **Стоимость** | **≈ $0.30–0.50/мес** | $5 кредитов |

---

## Обновление

Обычный `git push` в main → Railway автоматически пересоберёт и перезапустит.
Volume сохраняется → подписки и история — на месте.

---

## Полезные ссылки

- Регулировать частоту проверки: env `MONITOR_INTERVAL_MINUTES`
- Снизить шум при первом старте: env `SEED_RECENT_LOTS` (больше = меньше первых уведомлений)
- Лимит сообщений на пользователя за прогон: `MAX_NOTIFICATIONS_PER_RUN`
