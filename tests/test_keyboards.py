"""Тесты клавиатур.

Главный инвариант: callback_data ≤ 64 байт (жёсткий лимит Telegram —
документированный quirk проекта). Корейские названия в UTF-8 занимают
3 байта на символ, поэтому проверяем именно длину в байтах.
"""
from __future__ import annotations

from aiogram.types import InlineKeyboardMarkup, ReplyKeyboardMarkup

from bot import keyboards
from bot.scraper.models import REGION_KEYS
from bot.storage.db import UserFilter


def _all_callback_data(markup: InlineKeyboardMarkup):
    for row in markup.inline_keyboard:
        for btn in row:
            if btn.callback_data is not None:
                yield btn.callback_data


def _full_filter() -> UserFilter:
    return UserFilter(
        chat_id=1,
        manufacturers=["볼보", "두산디벨론", "현대"],
        subcategories=["100100", "100105"],
        regions=["경기", "강원"],
        min_grade=3,
        blacklist_keywords=["수리품"],
        year_from=2018, year_to=2024,
        price_min_won=20_000_000, price_max_won=200_000_000,
        hours_max=8000, skip_no_hours=True, require_photo=True,
        keyword="DX380",
    )


def _every_inline_markup() -> list[InlineKeyboardMarkup]:
    f = _full_filter()
    return [
        keyboards.main_menu(True),
        keyboards.main_menu(False),
        keyboards.search_menu(),
        keyboards.filter_menu(f),
        keyboards.filter_menu(UserFilter(chat_id=1)),     # пустой
        keyboards.pick_manufacturer(f.manufacturers),
        keyboards.pick_subcategories(f.subcategories),
        keyboards.pick_regions(REGION_KEYS),              # все регионы выбраны
        keyboards.pick_grade(3),
        keyboards.pick_grade(None),
        keyboards.pick_blacklist(),
        keyboards.pick_year("yf"),
        keyboards.pick_year("yt"),
        keyboards.pick_price(),
        keyboards.pick_price_min(),
        keyboards.pick_hours(),
        keyboards.pick_keyword(),
        keyboards.back_to_filter(),
        keyboards.back_to_main(),
        keyboards.search_more_kb(10),
        keyboards.search_empty_kb(10, has_seen=True),
        keyboards.search_empty_kb(10, has_seen=False),
    ]


def test_callback_data_within_64_bytes():
    for markup in _every_inline_markup():
        for cb in _all_callback_data(markup):
            assert len(cb.encode("utf-8")) <= 64, f"слишком длинный callback_data: {cb!r}"


def test_markups_have_buttons():
    for markup in _every_inline_markup():
        assert isinstance(markup, InlineKeyboardMarkup)
        assert any(markup.inline_keyboard), "пустая клавиатура"


def test_filter_menu_marks_active_conditions():
    """Заданные условия помечены 🟢, незаданные — ▫️."""
    active = keyboards.filter_menu(_full_filter())
    empty = keyboards.filter_menu(UserFilter(chat_id=1))
    active_labels = [b.text for row in active.inline_keyboard for b in row]
    empty_labels = [b.text for row in empty.inline_keyboard for b in row]
    assert any(lbl.startswith("🟢") for lbl in active_labels)
    # У пустого фильтра строки-условия не должны быть зелёными
    condition_rows = [lbl for lbl in empty_labels
                      if lbl.startswith("🟢") or lbl.startswith("▫️")]
    assert condition_rows and all(lbl.startswith("▫️") for lbl in condition_rows)


def test_reply_keyboard_has_nav_buttons():
    kb = keyboards.reply_keyboard()
    assert isinstance(kb, ReplyKeyboardMarkup)
    texts = {b.text for row in kb.keyboard for b in row}
    assert keyboards.NAV_TEXTS <= texts
    assert kb.resize_keyboard is True


def test_search_more_kb_offers_repeat():
    cbs = list(_all_callback_data(keyboards.search_more_kb(7)))
    assert "s:7" in cbs
