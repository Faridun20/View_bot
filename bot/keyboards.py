"""Inline-клавиатуры для меню бота.

Соглашение по callback_data (лимит 64 байта):
  m:<screen>            — навигация по экранам: main, search, filter
  s:<n>                 — search 5/10/20
  s:all:<n>             — search all 5/10/20
  s:forget              — забыть историю
  f:show / f:reset / f:back
  f:edit:<key>          — manufacturer / yf / yt / price / hours / keyword
  fm:<кр.название> / fm:any
  fyf:<год> / fyf:any
  fyt:<год> / fyt:any
  fp:<манвон> / fp:any / fp:custom
  fh:<часы> / fh:any / fh:custom
  fk:custom / fk:clear
"""
from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from bot.storage.db import UserFilter


def _btn(text: str, cb: str) -> InlineKeyboardButton:
    return InlineKeyboardButton(text=text, callback_data=cb)


def _kb(*rows: list[InlineKeyboardButton]) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=list(rows))


# ---------- главные экраны --------------------------------------------------

def main_menu() -> InlineKeyboardMarkup:
    return _kb(
        [_btn("🔍 Поиск лотов", "m:search")],
        [_btn("⚙️ Мой фильтр", "m:filter")],
        [_btn("❓ Помощь", "m:help")],
    )


def search_menu() -> InlineKeyboardMarkup:
    return _kb(
        [_btn("🆕 Новые лоты:", "m:noop")],
        [_btn("5", "s:5"), _btn("10", "s:10"), _btn("20", "s:20")],
        [_btn("🔄 С повторами:", "m:noop")],
        [_btn("5", "s:all:5"), _btn("10", "s:all:10"), _btn("20", "s:all:20")],
        [_btn("🗑 Забыть историю", "s:forget")],
        [_btn("← Назад", "m:main")],
    )


def filter_menu(f: UserFilter) -> InlineKeyboardMarkup:
    """Главный экран фильтра — короткие пиктограммы текущего значения."""
    return _kb(
        [_btn(f"🏭 {_short_mfr(f)}", "f:edit:m"),
         _btn(f"📅 {_short_year(f)}", "f:edit:y")],
        [_btn(f"💰 {_short_price(f)}", "f:edit:p"),
         _btn(f"⏱ {_short_hours(f)}", "f:edit:h")],
        [_btn(f"🔍 {_short_keyword(f)}", "f:edit:k")],
        [_btn("♻️ Сбросить весь фильтр", "f:reset")],
        [_btn("← Назад", "m:main")],
    )


# ---------- экраны выбора значения ------------------------------------------

# Точные корейские названия — то же, что в FSM filters.py
MANUFACTURERS = [
    ("현대", "Hyundai"), ("대우", "Daewoo"), ("두산디벨론", "Doosan"),
    ("삼성", "Samsung"), ("볼보", "Volvo"), ("한라", "Hanwha"),
    ("코마스", "Komatsu"), ("히타치", "Hitachi"), ("코벨코", "Kobelco"),
    ("캐타필라", "Caterpillar"), ("기타", "Прочие"),
]


def pick_manufacturer() -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = [
        [_btn("❌ Любой производитель", "fm:any")],
    ]
    for i in range(0, len(MANUFACTURERS), 3):
        rows.append([
            _btn(en, f"fm:{kr}") for kr, en in MANUFACTURERS[i:i+3]
        ])
    rows.append([_btn("← Назад", "m:filter")])
    return _kb(*rows)


def pick_year(role: str) -> InlineKeyboardMarkup:
    """role = 'yf' (год от) или 'yt' (год до)"""
    years = [2015, 2018, 2020, 2022, 2023, 2024, 2025, 2026]
    rows: list[list[InlineKeyboardButton]] = [[_btn("❌ Любой", f"f{role}:any")]]
    for i in range(0, len(years), 4):
        rows.append([_btn(str(y), f"f{role}:{y}") for y in years[i:i+4]])
    rows.append([_btn("← Назад", "m:filter")])
    return _kb(*rows)


def pick_price() -> InlineKeyboardMarkup:
    presets = [3000, 5000, 10000, 15000, 20000, 30000]   # в 만원
    rows: list[list[InlineKeyboardButton]] = [[_btn("❌ Любая цена", "fp:any")]]
    for i in range(0, len(presets), 3):
        rows.append([_btn(f"≤ {p:,}", f"fp:{p}") for p in presets[i:i+3]])
    rows.append([_btn("✏️ Своё значение", "fp:custom")])
    rows.append([_btn("← Назад", "m:filter")])
    return _kb(*rows)


def pick_hours() -> InlineKeyboardMarkup:
    presets = [2000, 3000, 5000, 8000, 12000, 20000]
    rows: list[list[InlineKeyboardButton]] = [[_btn("❌ Любые моточасы", "fh:any")]]
    for i in range(0, len(presets), 3):
        rows.append([_btn(f"≤ {p:,}", f"fh:{p}") for p in presets[i:i+3]])
    rows.append([_btn("✏️ Своё значение", "fh:custom")])
    rows.append([_btn("← Назад", "m:filter")])
    return _kb(*rows)


def pick_keyword() -> InlineKeyboardMarkup:
    return _kb(
        [_btn("✏️ Ввести ключевое слово", "fk:custom")],
        [_btn("❌ Очистить", "fk:clear")],
        [_btn("← Назад", "m:filter")],
    )


def back_to_filter() -> InlineKeyboardMarkup:
    return _kb([_btn("← К фильтру", "m:filter")])


def back_to_main() -> InlineKeyboardMarkup:
    return _kb([_btn("← В меню", "m:main")])


# ---------- короткие подписи для главного экрана фильтра -------------------

def _short_mfr(f: UserFilter) -> str:
    if not f.manufacturer:
        return "Любой"
    for kr, en in MANUFACTURERS:
        if kr == f.manufacturer:
            return en
    return f.manufacturer


def _short_year(f: UserFilter) -> str:
    if not f.year_from and not f.year_to:
        return "Любой год"
    a = str(f.year_from) if f.year_from else "—"
    b = str(f.year_to) if f.year_to else "—"
    return f"{a}…{b}"


def _short_price(f: UserFilter) -> str:
    if not f.price_max_won:
        return "Любая цена"
    return f"≤ {f.price_max_won // 10000:,} 만원".replace(",", " ")


def _short_hours(f: UserFilter) -> str:
    if f.hours_max is None:
        return "Любые часы"
    return f"≤ {f.hours_max:,} ч".replace(",", " ")


def _short_keyword(f: UserFilter) -> str:
    if not f.keyword:
        return "Без слова"
    kw = f.keyword if len(f.keyword) <= 15 else f.keyword[:14] + "…"
    return f'"{kw}"'
