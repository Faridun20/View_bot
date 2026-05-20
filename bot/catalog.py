"""Сервисный слой доступа к каталогу сайта.

Единая точка обхода подкатегорий и загрузки карточек. Раньше эта логика
дублировалась в `monitor._scan_categories` и `search._scan_with_previews`
(в коде даже стоял комментарий «дублируем обход целиком»).

Все функции здесь **синхронные** (как и весь scraper) — из async-кода их
вызывают через `asyncio.to_thread`, иначе блокируется event loop, а sync
Playwright внутри `get_session` падает.
"""
from __future__ import annotations

import logging

from bot import config
from bot.scraper import get_session, parse_item_page, parse_listing_page
from bot.scraper.models import Listing, ListingPreview, target_subcategories

logger = logging.getLogger(__name__)


def scan_previews() -> list[ListingPreview]:
    """Обходит целевые подкатегории (с учётом INCLUDE_PARTS) и возвращает
    уникальные превью, отсортированные по убыванию pid (свежие — первыми).

    Сбой по одной подкатегории не прерывает обход остальных.
    """
    sess = get_session()
    by_pid: dict[int, ListingPreview] = {}
    for cate_code in target_subcategories(include_parts=config.INCLUDE_PARTS):
        try:
            resp = sess.get(f"/sub8_1_s.html?cate_code={cate_code}&limit=70&page=1")
            for prev in parse_listing_page(resp.text, cate_code=cate_code):
                # Если pid встречается в нескольких подкатегориях — оставляем
                # первое попадание (порядок обхода target_subcategories).
                by_pid.setdefault(prev.pid, prev)
        except Exception as e:
            logger.warning("catalog.scan_previews: cate_code=%s: %s", cate_code, e)
            logger.debug("traceback:", exc_info=True)
    return sorted(by_pid.values(), key=lambda p: p.pid, reverse=True)


def scan_categories() -> dict[int, str | None]:
    """Сводка обхода в виде {pid: cate_code} — для дедупликации по seen_pids.

    Поведенчески эквивалентна старой `monitor._scan_categories`, но
    переиспользует единый `scan_previews` вместо собственного обхода.
    """
    return {p.pid: p.cate_code for p in scan_previews()}


def fetch_item(pid: int) -> Listing | None:
    """Загружает и парсит карточку лота. None при сетевой/парсерной ошибке."""
    sess = get_session()
    try:
        resp = sess.get(f"/sub8_1_vvv.html?pid={pid}")
        return parse_item_page(resp.text, pid)
    except Exception as e:
        logger.warning("catalog.fetch_item: pid=%s: %s", pid, e)
        logger.debug("traceback:", exc_info=True)
        return None


def fetch_latest() -> Listing | None:
    """Самый свежий лот среди целевых подкатегорий (для /test).

    Берёт первое превью (максимальный pid) и догружает его карточку.
    """
    previews = scan_previews()
    if not previews:
        return None
    return fetch_item(previews[0].pid)
