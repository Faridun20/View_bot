"""Тесты бизнес-логики фильтрации."""
from __future__ import annotations

import pytest

from bot import config
from bot.monitor import matches
from bot.scraper.models import Listing, ListingPreview
from bot.storage.db import UserFilter


@pytest.fixture
def good():
    """Базовый «хороший» лот: Volvo 2022, 1.3+, 경기, A+, 100M, 5000ч, с описанием."""
    return Listing(
        pid=1, url="x",
        category_path="굴삭기/어태치부속 > 굴삭기 1.3 ㎥ 이상",
        manufacturer="볼보", model="EC480", year="2022.05",
        grade="A+급", region="경기도",
        price_won=100_000_000, hours=5000,
        description="좋은 상태",
        photos=["https://x/a.jpg"],
    )


@pytest.fixture(autouse=True)
def parts_disabled(monkeypatch):
    monkeypatch.setattr(config, "INCLUDE_PARTS", False)


def test_empty_filter_passes(good):
    assert matches(good, UserFilter(chat_id=1))


def test_filter_by_single_manufacturer(good):
    f = UserFilter(chat_id=1, manufacturers=["현대"])
    assert not matches(good, f)
    f.manufacturers = ["볼보"]
    assert matches(good, f)


def test_filter_by_multiple_manufacturers(good):
    f = UserFilter(chat_id=1, manufacturers=["볼보", "현대", "두산디벨론"])
    assert matches(good, f)
    f.manufacturers = ["현대", "두산디벨론"]
    assert not matches(good, f)


def test_filter_by_subcategory(good):
    f = UserFilter(chat_id=1, subcategories=["100104"])    # только мини
    assert not matches(good, f)
    f.subcategories = ["100100"]                            # 1.3+
    assert matches(good, f)


def test_filter_by_region(good):
    f = UserFilter(chat_id=1, regions=["서울", "부산"])
    assert not matches(good, f)
    f.regions = ["경기"]
    assert matches(good, f)


def test_filter_by_grade(good):
    # Требуем A+ — проходит
    assert matches(good, UserFilter(chat_id=1, min_grade=4))
    # Bad-grade лот
    bad = Listing(pid=2, url="x", grade="B급", category_path=good.category_path,
                  manufacturer="볼보", year="2022.01", region="경기도")
    assert not matches(bad, UserFilter(chat_id=1, min_grade=4))


def test_filter_blacklist_in_description(good):
    f = UserFilter(chat_id=1, blacklist_keywords=["수리품"])
    bad = Listing(pid=3, url="x", category_path=good.category_path,
                  manufacturer="볼보", year="2022.01", region="경기도",
                  description="수리품 입니다", price_won=100_000_000)
    assert not matches(bad, f)
    assert matches(good, f)         # у good в описании нет "수리품"


def test_filter_price_max_min(good):
    f = UserFilter(chat_id=1, price_max_won=150_000_000)
    assert matches(good, f)         # 100M < 150M
    f.price_max_won = 50_000_000
    assert not matches(good, f)     # 100M > 50M

    f = UserFilter(chat_id=1, price_min_won=200_000_000)
    assert not matches(good, f)     # 100M < 200M


def test_filter_skip_no_hours(good):
    f = UserFilter(chat_id=1, skip_no_hours=True)
    assert matches(good, f)         # часы есть
    nohour = Listing(pid=4, url="x", category_path=good.category_path,
                     manufacturer="볼보", year="2022.01", region="경기도",
                     hours=None)
    assert not matches(nohour, f)


def test_filter_hours_max(good):
    f = UserFilter(chat_id=1, hours_max=3000)
    assert not matches(good, f)     # 5000 > 3000
    f.hours_max = 8000
    assert matches(good, f)


def test_filter_year_range(good):
    f = UserFilter(chat_id=1, year_from=2020, year_to=2024)
    assert matches(good, f)
    f.year_from = 2023
    assert not matches(good, f)
    # Лот без года — отсекается, если фильтр выставлен
    noyear = Listing(pid=5, url="x", category_path=good.category_path,
                     manufacturer="볼보", year=None, region="경기도")
    assert not matches(noyear, UserFilter(chat_id=1, year_from=2020))


def test_filter_require_photo(good):
    f = UserFilter(chat_id=1, require_photo=True)
    assert matches(good, f)
    nophoto = Listing(pid=6, url="x", photos=[],
                      category_path=good.category_path,
                      manufacturer="볼보", year="2022.01", region="경기도")
    assert not matches(nophoto, f)


def test_filter_keyword(good):
    f = UserFilter(chat_id=1, keyword="EC480")
    assert matches(good, f)
    f.keyword = "DX380"
    assert not matches(good, f)
    # case-insensitive
    f.keyword = "ec480"
    assert matches(good, f)


def test_parts_blocked_by_global_flag(good, monkeypatch):
    parts = Listing(pid=7, url="x",
                    category_path="굴삭기/어태치부속 > 어태치먼트",
                    manufacturer="기타")
    # При INCLUDE_PARTS=False парты отсекаются
    monkeypatch.setattr(config, "INCLUDE_PARTS", False)
    assert not matches(parts, UserFilter(chat_id=1))
    # При INCLUDE_PARTS=True пропускаются
    monkeypatch.setattr(config, "INCLUDE_PARTS", True)
    assert matches(parts, UserFilter(chat_id=1))


# ---------- previewfilter (search) ----------

def test_passes_preview_subcategory():
    from bot.handlers.search import _passes_preview
    f = UserFilter(chat_id=1, subcategories=["100104"])
    assert not _passes_preview(ListingPreview(pid=1, cate_code="100100"), f)
    assert _passes_preview(ListingPreview(pid=1, cate_code="100104"), f)


def test_passes_preview_price():
    from bot.handlers.search import _passes_preview
    f = UserFilter(chat_id=1, price_max_won=50_000_000)
    assert not _passes_preview(ListingPreview(pid=1, price_raw="6,000만원"), f)
    assert _passes_preview(ListingPreview(pid=1, price_raw="3,000만원"), f)


def test_passes_preview_photo():
    from bot.handlers.search import _passes_preview
    f = UserFilter(chat_id=1, require_photo=True)
    assert _passes_preview(ListingPreview(pid=1, has_photo=True), f)
    assert not _passes_preview(ListingPreview(pid=1, has_photo=False), f)
    # has_photo=None — превью не отсекает, доверяет полной карточке
    assert _passes_preview(ListingPreview(pid=1, has_photo=None), f)
