"""Живой тест парсера 4396200.com.

Что делает:
1. Открывает сессию (использует сохранённую cookie CUPID).
2. Идёт во все 8 подкатегорий «Экскаваторов», парсит первую страницу.
3. Печатает количество найденных pid в каждой подкатегории и сводный топ.
4. Берёт 3 самых свежих pid (из всех подкатегорий) и парсит их карточки.
5. Печатает все распарсенные поля.
6. Пробует скачать первое фото с каждой карточки — проверка, что фото отдаются.
"""
from __future__ import annotations

import logging
import sys
import time
from pathlib import Path

from bot.scraper import get_session, parse_item_page, parse_listing_page
from bot.scraper.models import EXCAVATOR_SUBCATEGORIES

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

OUT_DIR = Path("scrape_test_out")
OUT_DIR.mkdir(exist_ok=True)


def main() -> int:
    sess = get_session()
    all_pids: list[tuple[int, str]] = []   # (pid, cate_code)

    print("=" * 70)
    print("ОБХОД ПОДКАТЕГОРИЙ ЭКСКАВАТОРОВ")
    print("=" * 70)
    for cate_code, (kr, ru) in EXCAVATOR_SUBCATEGORIES.items():
        url = f"/sub8_1_s.html?cate_code={cate_code}&limit=70&page=1"
        t0 = time.time()
        try:
            resp = sess.get(url)
        except Exception as e:
            print(f"  [ERR] {cate_code} {ru}: {e}")
            continue
        previews = parse_listing_page(resp.text, cate_code=cate_code)
        dt = time.time() - t0
        max_pid = max((p.pid for p in previews), default=0)
        print(f"  {cate_code} | {ru:<35} | {len(previews):>3} лотов | "
              f"max pid {max_pid} | {dt:.2f}s | {len(resp.content)/1024:.0f} КБ")
        for p in previews:
            all_pids.append((p.pid, cate_code))

    print()
    if not all_pids:
        print("[FAIL] Не найдено ни одного лота — парсер сломан или сайт недоступен.")
        return 1

    # Дедуп + топ-3 по pid
    unique = sorted({pid: code for pid, code in all_pids}.items(), reverse=True)
    print(f"Всего уникальных pid в первых страницах: {len(unique)}")
    print(f"Топ-3 самых свежих pid: {[p for p, _ in unique[:3]]}")

    print()
    print("=" * 70)
    print("ПАРСИНГ КАРТОЧЕК (top-3)")
    print("=" * 70)
    for pid, cate in unique[:3]:
        url = f"/sub8_1_vvv.html?pid={pid}"
        try:
            resp = sess.get(url)
        except Exception as e:
            print(f"  [ERR] pid={pid}: {e}")
            continue
        item = parse_item_page(resp.text, pid)
        print()
        print(f"--- pid={pid}  ({cate}) ---")
        print(f"  URL:           {item.url}")
        print(f"  status:        {item.status}")
        print(f"  manufacturer:  {item.manufacturer}")
        print(f"  model:         {item.model}")
        print(f"  year:          {item.year}")
        print(f"  grade:         {item.grade}")
        print(f"  region:        {item.region}")
        print(f"  price_raw:     {item.price_raw}")
        print(f"  price_won:     {item.price_won:,}" if item.price_won else "  price_won:     —")
        print(f"  hours_raw:     {item.hours_raw!r}")
        print(f"  hours:         {item.hours}")
        print(f"  tonnage:       {item.tonnage}")
        print(f"  seller:        {item.seller}")
        print(f"  phone:         {item.phone}")
        print(f"  posted_at:     {item.posted_at}")
        print(f"  photos:        {len(item.photos)} шт.")
        if item.photos:
            print(f"    main_photo:  {item.main_photo()}")
        if item.description:
            desc = item.description[:100].replace("\n", " ")
            print(f"  description:   {desc}{'…' if len(item.description) > 100 else ''}")

        # Скачать первое фото — убедиться, что отдаётся.
        if item.main_photo():
            try:
                r = sess.get(item.main_photo())
                fname = OUT_DIR / f"pid_{pid}_main{Path(item.main_photo()).suffix}"
                fname.write_bytes(r.content)
                print(f"  [фото сохранено] {fname} ({len(r.content)/1024:.0f} КБ)")
            except Exception as e:
                print(f"  [ERR фото] {e}")

    print()
    print("=" * 70)
    print("ГОТОВО")
    print("=" * 70)
    return 0


if __name__ == "__main__":
    sys.exit(main())
