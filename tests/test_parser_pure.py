"""Чистые юнит-тесты парсера: без зависимостей от HTML."""
from __future__ import annotations

import pytest

from bot.scraper.models import (
    grade_label, grade_rank, looks_like_parts, normalize_region,
    region_matches, target_subcategories,
)
from bot.scraper.parser import _parse_price, _parse_hours


# ---------- цена ----------

@pytest.mark.parametrize("raw, expected", [
    ("6,000만원",       60_000_000),
    ("13,800만원",      138_000_000),
    ("1억",             100_000_000),
    ("1.3억",           130_000_000),
    ("2.5억",           250_000_000),
    ("1억3천만원",        130_000_000),
    ("2억5,000만원",     250_000_000),
    ("3천만",           30_000_000),
    ("",                None),
    ("문의",            None),
    (None,              None),
])
def test_parse_price(raw, expected):
    assert _parse_price(raw) == expected


# ---------- моточасы ----------

@pytest.mark.parametrize("raw, expected", [
    ("5000h",        5000),
    ("5,000hr",      5000),
    ("8000시간",     8000),
    ("12000",        12000),
    ("",             None),
    (None,           None),
])
def test_parse_hours(raw, expected):
    assert _parse_hours(raw) == expected


# ---------- грейд ----------

@pytest.mark.parametrize("g, rank", [
    ("A+급", 4), ("A급", 3), ("B+급", 2), ("B급", 1),
    ("a+급", 4),                 # case-insensitive
    ("A+", 4),                   # без 급
    ("", 0), (None, 0), ("foo", 0),
])
def test_grade_rank(g, rank):
    assert grade_rank(g) == rank


def test_grade_label_roundtrip():
    for r in (4, 3, 2, 1):
        assert grade_rank(grade_label(r)) == r


# ---------- регион ----------

@pytest.mark.parametrize("raw, norm", [
    ("강원도",            "강원"),
    ("서울특별시",         "서울"),
    ("경기 안성",          "경기"),
    ("부산광역시",         "부산"),
    ("제주특별자치도",      "제주"),
    ("",                  None),
    (None,                None),
])
def test_normalize_region(raw, norm):
    assert normalize_region(raw) == norm


def test_region_matches_empty_filter_passes_all():
    assert region_matches("강원도", [])
    assert region_matches(None, [])
    assert region_matches("강원도", None)


def test_region_matches_unknown_region_passes():
    # Лучше пропустить, чем отсечь по непарсящемуся региону.
    assert region_matches(None, ["서울"])
    assert region_matches("", ["서울"])


def test_region_matches_strict():
    assert region_matches("경기도", ["경기", "서울"])
    assert not region_matches("부산광역시", ["경기", "서울"])


# ---------- looks_like_parts ----------

def test_looks_like_parts_leaf_only():
    assert looks_like_parts("굴삭기/어태치부속 > 어태치먼트")
    assert looks_like_parts("굴삭기/어태치부속 > 굴삭기부속")
    # Родительская группа содержит '어태치부속', но это не лист — не парт
    assert not looks_like_parts("굴삭기/어태치부속 > 굴삭기 1.3 ㎥ 이상")
    assert not looks_like_parts("굴삭기/어태치부속 > 미니굴삭기")
    assert not looks_like_parts(None)
    assert not looks_like_parts("")


# ---------- target_subcategories ----------

def test_target_subcategories_excludes_parts_by_default():
    subs = target_subcategories(include_parts=False)
    assert "100100" in subs
    assert "100104" in subs
    assert "100106" not in subs     # 어태치먼트
    assert "100107" not in subs     # 굴삭기부속


def test_target_subcategories_with_parts():
    subs = target_subcategories(include_parts=True)
    assert "100106" in subs and "100107" in subs
    assert len(subs) == 8
