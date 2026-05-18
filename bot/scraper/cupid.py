"""Обновление cookie CUPID через Playwright.

Сайт 4396200.com защищён самописным JS-челленджем «Cupid»: при первом заходе
сервер отдаёт страницу, JS которой через slowAES.decrypt вычисляет cookie
CUPID и редиректит. Cookie живёт ~24 часа. Этот модуль один раз запускает
безголовый Chromium, проходит проверку и сохраняет storage_state.json.

Используется только когда обычный requests-запрос получил заглушку (то есть
кука истекла или ещё не получена). В нормальной работе не вызывается.
"""
from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

BASE = "https://www.4396200.com"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)


def refresh_cupid_cookie(storage_path: Path) -> None:
    """Запускает headless-браузер, проходит Cupid и сохраняет storage_state."""
    # Импорт внутри: Playwright тяжёлый, не нужен в горячем пути requests.
    from playwright.sync_api import sync_playwright

    storage_path.parent.mkdir(parents=True, exist_ok=True)

    logger.info("Cupid: запускаю Playwright для обновления cookie")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(user_agent=USER_AGENT, locale="ko-KR")
        page = context.new_page()
        # Заходим на реальную страницу с контентом, а не на корень: Cupid
        # отрабатывает на первом запросе, дальше редирект ?ckattempt=1, а
        # сразу следом мы ждём, чтобы реальный HTML каталога подгрузился
        # (на нём есть стабильный маркер 'mc_tx' — класс карточек лотов).
        page.goto(f"{BASE}/sub8_1_s.html?cate_code=100100&limit=70&page=1",
                  wait_until="networkidle", timeout=60000)
        try:
            page.wait_for_function(
                "document.body.innerText.length > 5000 && "
                "!document.body.innerText.includes('보안절차')",
                timeout=15000,
            )
        except Exception as e:
            logger.warning("Cupid: страница не «прогрелась» за 15с: %s", e)
        context.storage_state(path=str(storage_path))
        browser.close()
    logger.info("Cupid: cookie сохранена в %s", storage_path)
