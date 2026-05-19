"""Юнит-тесты парсера на сохранённых HTML-снапшотах."""
from __future__ import annotations

from bot.scraper.parser import parse_item_page, parse_listing_page


def test_parse_listing_page_finds_listings(recon_dir):
    html = (recon_dir / "21_subcat_100100_excavators_13.html").read_text(encoding="utf-8")
    previews = parse_listing_page(html, cate_code="100100")
    assert len(previews) >= 50, f"ожидаем много лотов, получили {len(previews)}"
    assert all(p.pid > 0 for p in previews)
    # Сортировка по pid убывающе
    pids = [p.pid for p in previews]
    assert pids == sorted(pids, reverse=True)


def test_parse_listing_has_photo_flag(recon_dir):
    html = (recon_dir / "21_subcat_100100_excavators_13.html").read_text(encoding="utf-8")
    previews = parse_listing_page(html, cate_code="100100")
    with_photo = [p for p in previews if p.has_photo is True]
    without_photo = [p for p in previews if p.has_photo is False]
    # На этой странице есть pid=9151495 без фото (заглушка img/sub/s9_i2.png)
    assert with_photo, "должны быть лоты с фото"
    assert any(p.pid == 9151495 for p in without_photo), \
        "pid=9151495 известно без фото в снапшоте"


def test_parse_item_page_full_fields(recon_dir):
    pid = 9146671
    html = (recon_dir / f"25_item_{pid}.html").read_text(encoding="utf-8")
    item = parse_item_page(html, pid=pid)
    assert item.pid == pid
    assert item.model == "380D"
    assert item.manufacturer == "볼보"
    assert item.year == "2014.01"
    assert item.grade == "A+급"
    assert item.region == "강원도"
    assert item.price_raw == "6,000만원"
    assert item.price_won == 60_000_000
    assert item.phone == "010-6665-6200"
    assert item.posted_at == "2026-05-13 10:21:22"
    assert "어태치부속" in (item.category_path or "")


def test_parse_item_page_with_photos(recon_dir):
    pid = 9094615
    html = (recon_dir / f"26_item_{pid}.html").read_text(encoding="utf-8")
    item = parse_item_page(html, pid=pid)
    assert item.photos, "у этой карточки должны быть фото"
    assert all("/upload/" in p for p in item.photos)
