"""HTTP-клиент для 4396200.com с автоматическим обновлением CUPID-cookie."""
from __future__ import annotations

import json
import logging
from pathlib import Path

import requests

from bot.scraper.cupid import BASE, USER_AGENT, refresh_cupid_cookie

logger = logging.getLogger(__name__)

DEFAULT_STORAGE = Path("recon_out/storage_state.json")
# Заглушка Cupid: ~1.5 КБ, содержит /cupid.js и slowAES. Берём максимально
# устойчивые маркеры, которые не зависят от кодировки.
CUPID_MARKERS = ("/cupid.js", "slowAES", "CUPID=")


def _looks_like_cupid_stub(resp: requests.Response) -> bool:
    if len(resp.content) > 5000:
        return False
    body = resp.content[:5000].decode("ascii", errors="ignore")
    return any(m in body for m in CUPID_MARKERS)


class CupidSession:
    """requests.Session с куками CUPID, прозрачное обновление при истечении."""

    def __init__(self, storage_path: Path = DEFAULT_STORAGE) -> None:
        self.storage_path = storage_path
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": USER_AGENT,
            "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.8",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Referer": BASE + "/",
        })
        self._load_cookies()

    def _load_cookies(self) -> None:
        if not self.storage_path.exists():
            logger.info("storage_state.json не найден, запускаю Cupid")
            refresh_cupid_cookie(self.storage_path)

        data = json.loads(self.storage_path.read_text(encoding="utf-8"))
        cookie_count = 0
        for c in data.get("cookies", []):
            # Playwright-формат → cookies в requests-сессии
            self.session.cookies.set(
                name=c["name"],
                value=c["value"],
                domain=c.get("domain", ".4396200.com"),
                path=c.get("path", "/"),
            )
            cookie_count += 1
        logger.debug("Загружено cookies: %d", cookie_count)

    def _refresh(self) -> None:
        refresh_cupid_cookie(self.storage_path)
        self.session.cookies.clear()
        self._load_cookies()

    def get(self, url: str, *, refresh_budget: int = 2, timeout: int = 30) -> requests.Response:
        """GET с автообновлением cookie, если сервер вернул заглушку Cupid.

        refresh_budget — сколько раз ещё можно перевыпустить cookie. 0 =
        запрещено (возвращаем что вернулось).
        """
        if not url.startswith("http"):
            url = BASE + url if url.startswith("/") else f"{BASE}/{url}"

        resp = self.session.get(url, timeout=timeout)
        resp.raise_for_status()
        # Сервер не присылает charset; для HTML-страниц форсим UTF-8.
        if "image" not in resp.headers.get("Content-Type", ""):
            resp.encoding = "utf-8"

        if _looks_like_cupid_stub(resp) and refresh_budget > 0:
            logger.warning("Cupid-заглушка для %s (%d б), обновляю cookie (budget=%d)",
                           url, len(resp.content), refresh_budget)
            self._refresh()
            return self.get(url, refresh_budget=refresh_budget - 1, timeout=timeout)

        return resp


_singleton: CupidSession | None = None


def get_session() -> CupidSession:
    """Глобальный singleton — переиспользовать соединения и cookies."""
    global _singleton
    if _singleton is None:
        _singleton = CupidSession()
    return _singleton
