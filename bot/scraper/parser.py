"""BeautifulSoup-парсинг страниц 4396200.com.

Две точки входа:
- parse_listing_page(html, cate_code) -> list[ListingPreview] — для sub8_1_s.html
- parse_item_page(html, pid)         -> Listing               — для sub8_1_vvv.html?pid=…
"""
from __future__ import annotations

import re
from typing import Iterable
from urllib.parse import urljoin

from bs4 import BeautifulSoup, Tag

from bot.scraper.models import Listing, ListingPreview

BASE = "https://www.4396200.com"

PID_RE = re.compile(r"sub8_1_vvv\.html\?pid=(\d+)")

# «6,000만원» → 60 000 000 KRW. 만원 = 10 000 ВОН.
PRICE_RE = re.compile(r"([\d,]+)\s*만원")

# «운행» может быть «5000hr», «5000h», «5000시간», «5,000 hours», «5000H/r»…
HOURS_RE = re.compile(r"([\d,\.]+)\s*(?:h|hr|hour|시간|H/?r|시)", re.IGNORECASE)


# ---------- Список лотов ----------------------------------------------------

def parse_listing_page(html: str, cate_code: str | None = None) -> list[ListingPreview]:
    """Извлекает все объявления из страницы списка (грид + табличный вариант).

    Возвращает уникальные ListingPreview, упорядоченные по pid убывающе
    (новые первыми). pid из href достаточно — это primary key.
    """
    soup = BeautifulSoup(html, "lxml")

    # Берём ВСЕ ссылки на карточки лотов: и в гриде, и в таблице.
    items: dict[int, ListingPreview] = {}
    for a in soup.select("a[href*='sub8_1_vvv.html?pid=']"):
        m = PID_RE.search(a.get("href", ""))
        if not m:
            continue
        pid = int(m.group(1))
        if pid not in items:
            items[pid] = ListingPreview(pid=pid, cate_code=cate_code)

    # Заполняем превью-поля из грида (где они стабильно лежат).
    # Структура повторяющегося блока:
    #   <div class="mc_tx1 t10"><a href=…>МОДЕЛЬ</a></div>
    #   <div class="mc_tx2"><a href=…><strong>ЦЕНА</strong></a></div>
    #   <div class="mc_tx2"><a href=…>ГРЕЙД</a></div>
    for tx1 in soup.select("div.mc_tx1 a[href*='pid=']"):
        m = PID_RE.search(tx1.get("href", ""))
        if not m:
            continue
        pid = int(m.group(1))
        prev = items.setdefault(pid, ListingPreview(pid=pid, cate_code=cate_code))
        if not prev.model:
            prev.model = tx1.get_text(strip=True) or None

    # Цены — через div.mc_tx2 strong
    for tx2 in soup.select("div.mc_tx2 a[href*='pid=']"):
        m = PID_RE.search(tx2.get("href", ""))
        if not m:
            continue
        pid = int(m.group(1))
        prev = items.setdefault(pid, ListingPreview(pid=pid, cate_code=cate_code))
        text = tx2.get_text(" ", strip=True)
        if "만원" in text and not prev.price_raw:
            prev.price_raw = text.replace("\xa0", " ").strip()
        elif "급" in text and not prev.grade:
            prev.grade = text.strip()

    # Сортировка: свежие (большой pid) первыми
    return sorted(items.values(), key=lambda x: x.pid, reverse=True)


# ---------- Карточка лота ---------------------------------------------------

# Корейская метка → имя поля в Listing.
ITEM_FIELDS = {
    "구분":        "status",
    "제작년월":    "year",
    "분류":        "category_path",
    "상태":        "grade",
    "제작사":      "manufacturer",
    "위치":        "region",
    "모델명":      "model",
    "가격":        "price_raw",
    "상호":        "seller",
    "연락처":      "phone",
    "엔진":        "engine",
    "밋션":        "transmission",
    "톤수":        "tonnage",
    "운행":        "hours_raw",
    "할부여부":    "installment",
    "할부여부/원금": "installment",
    "사고여부":    "accident",
    "하부타입":    "undercarriage_type",
    "하부상태":    "undercarriage_state",
}


def parse_item_page(html: str, pid: int) -> Listing:
    soup = BeautifulSoup(html, "lxml")
    listing = Listing(pid=pid, url=f"{BASE}/sub8_1_vvv.html?pid={pid}")

    # 1) Главная таблица s161_table (или fallback: первая таблица в .vip_item-блоке)
    main_table = soup.select_one("table.s161_table") or soup.find("table")
    if main_table:
        for row in main_table.select("tr"):
            cells = row.find_all(["th", "td"], recursive=False)
            # Структура: th td th td (две пары на строку)
            i = 0
            while i + 1 < len(cells):
                th = cells[i]
                td = cells[i + 1]
                if th.name == "th" and td.name == "td":
                    label = th.get_text(strip=True)
                    value = td.get_text(" ", strip=True) or None
                    attr = ITEM_FIELDS.get(label)
                    if attr:
                        setattr(listing, attr, value)
                i += 2

    # 2) shop_table — дата размещения и описание
    shop = soup.select_one("table.shop_table")
    if shop:
        # Дата лежит в td с классом 'ar' (right-aligned) в первой строке.
        ar_td = shop.select_one("td.ar")
        if ar_td:
            text = ar_td.get_text(" ", strip=True)
            # Формат «2026-05-13 10:21:22»; иногда могут добавить «작성자 :» и т.п.
            m = re.search(r"\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}", text)
            listing.posted_at = m.group(0) if m else text

        # Описание — в .product_comment или в td colspan=2
        desc = shop.select_one(".product_comment")
        if desc is None:
            for td in shop.select("td"):
                if td.get("colspan") == "2":
                    desc = td
                    break
        if desc:
            listing.description = desc.get_text(" ", strip=True) or None

    # 3) Фото из ul.s81_vvv (галерея)
    for img in soup.select("ul.s81_vvv li img[src]"):
        src = img.get("src")
        if src and "/img/sub/" not in src:        # игнор дефолтной заглушки
            listing.photos.append(urljoin(BASE, src))

    # 4) Парсим производные числовые поля
    listing.price_won = _parse_price(listing.price_raw)
    listing.hours = _parse_hours(listing.hours_raw)

    return listing


# ---------- helpers ---------------------------------------------------------

def _parse_price(raw: str | None) -> int | None:
    if not raw:
        return None
    m = PRICE_RE.search(raw)
    if not m:
        return None
    digits = m.group(1).replace(",", "")
    try:
        return int(digits) * 10000   # 만원 → ВОН
    except ValueError:
        return None


def _parse_hours(raw: str | None) -> int | None:
    if not raw:
        return None
    # 1) Сначала пытаемся выдрать число с единицей измерения.
    m = HOURS_RE.search(raw)
    if m:
        digits = m.group(1).replace(",", "").split(".")[0]
        try:
            return int(digits)
        except ValueError:
            return None
    # 2) Если в строке только цифры (продавец указал «5000» без единиц).
    digits = re.sub(r"[^\d]", "", raw)
    if digits and len(digits) <= 6:               # отбрасываем явно левые
        try:
            return int(digits)
        except ValueError:
            return None
    return None


def extract_pids(urls: Iterable[str]) -> list[int]:
    """Утилита: достать pid-ы из любых ссылок sub8_1_vvv.html?pid=…"""
    out: list[int] = []
    for url in urls:
        m = PID_RE.search(url)
        if m:
            out.append(int(m.group(1)))
    return out
