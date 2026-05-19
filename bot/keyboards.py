"""Inline-клавиатуры для меню бота.

Соглашение по callback_data (лимит 64 байта):
  m:<screen>            — навигация: main, search, filter, help, noop
  s:<n>                 — search 5/10/20
  s:all:<n>             — search all
  s:forget              — забыть историю

  f:edit:<key>          — переход к редактированию (m/y/p/h/k/s/r/g/b/no-h)
  f:reset               — сброс всего фильтра

  fm:t:<кр>             — toggle производителя
  fm:clear / fm:done

  fs:t:<cate>           — toggle подкатегории-размера
  fs:clear / fs:done

  fr:t:<key>            — toggle региона
  fr:clear / fr:done

  fg:<rank> / fg:any    — минимальный грейд (1..4 или any)

  fb:custom / fb:clear  — чёрный список (ввод / очистка)

  fyf:<год> / fyf:any   — год от
  fyt:<год> / fyt:any   — год до
  fp:<манвон> / fp:any / fp:custom — макс. цена
  fpmn:<манвон> / fpmn:any / fpmn:custom — мин. цена
  fh:<часы> / fh:any / fh:custom    — макс. моточасы
  fnoh:t                — toggle «не присылать лоты без моточасов»
  fk:custom / fk:clear  — ключевое слово
"""
from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from bot.scraper.models import (
    EXCAVATOR_SUBCATEGORIES,
    PARTS_SUBCATEGORIES,
    REGIONS,
    grade_label,
)
from bot.storage.db import UserFilter


def _btn(text: str, cb: str) -> InlineKeyboardButton:
    return InlineKeyboardButton(text=text, callback_data=cb)


def _kb(*rows: list[InlineKeyboardButton]) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=list(rows))


# ---------- главные экраны --------------------------------------------------

def main_menu(auto_on: bool = True) -> InlineKeyboardMarkup:
    """Главное меню — 2 ряда по 2 кнопки + одна полная.

    Авто-уведомления вынесены в первый ряд как ключевой переключатель
    (часто ли работает мониторинг — основной вопрос пользователя).
    """
    bell_label = "🔔 Авто: ВКЛ" if auto_on else "🔕 Авто: ВЫКЛ"
    return _kb(
        [_btn("🔍 Поиск", "m:search"),
         _btn("⚙️ Фильтр", "m:filter")],
        [_btn(bell_label, "m:auto:t"),
         _btn("🔖 Избранное", "m:favs")],
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
    no_hours_label = "🚫 без часов" if f.skip_no_hours else "✅ без часов"
    photo_label = "📷 только с фото" if f.require_photo else "🖼 любые (с/без фото)"
    return _kb(
        [_btn(f"📏 {_short_subs(f)}", "f:edit:s")],
        [_btn(f"🏭 {_short_mfr(f)}", "f:edit:m"),
         _btn(f"📍 {_short_region(f)}", "f:edit:r")],
        [_btn(f"🏆 {_short_grade(f)}", "f:edit:g"),
         _btn(f"📅 {_short_year(f)}", "f:edit:y")],
        [_btn(f"💰 {_short_price(f)}", "f:edit:p"),
         _btn(f"⏱ {_short_hours(f)}", "f:edit:h")],
        [_btn(f"🔍 {_short_keyword(f)}", "f:edit:k"),
         _btn(f"🚫 {_short_blacklist(f)}", "f:edit:b")],
        [_btn(no_hours_label, "fnoh:t"),
         _btn(photo_label, "fph:t")],
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


def pick_manufacturer(selected: list[str]) -> InlineKeyboardMarkup:
    """Multi-select: чекбоксы для производителей."""
    selected_set = set(selected)
    rows: list[list[InlineKeyboardButton]] = []
    for i in range(0, len(MANUFACTURERS), 3):
        row = []
        for kr, en in MANUFACTURERS[i:i+3]:
            mark = "☑️" if kr in selected_set else "▫️"
            row.append(_btn(f"{mark} {en}", f"fm:t:{kr}"))
        rows.append(row)
    rows.append([_btn("❌ Очистить все", "fm:clear"),
                 _btn("✅ Готово", "fm:done")])
    rows.append([_btn("← Назад", "m:filter")])
    return _kb(*rows)


def pick_subcategories(selected: list[str]) -> InlineKeyboardMarkup:
    """Multi-select: подкатегории-размеры экскаваторов.

    Сверху — две shortcut-кнопки для быстрого выбора «только колёсные»
    (100105) или «только гусеничные» (100100-100104). Они переписывают
    набор одним кликом.
    """
    selected_set = set(selected)
    rows: list[list[InlineKeyboardButton]] = []

    # Shortcuts по типу хода
    rows.append([
        _btn("🛞 Только колёсные",   "fs:chassis:wheeled"),
        _btn("🦂 Только гусеничные", "fs:chassis:tracked"),
    ])

    # Сами подкатегории-размеры (только «машинные»)
    for cate, (kr, ru) in EXCAVATOR_SUBCATEGORIES.items():
        if cate in PARTS_SUBCATEGORIES:
            continue
        mark = "☑️" if cate in selected_set else "▫️"
        # 🛞 — визуальный маркер колёсных (чтобы было видно в общем списке)
        icon = " 🛞" if cate == "100105" else ""
        rows.append([_btn(f"{mark} {ru}{icon}", f"fs:t:{cate}")])

    rows.append([_btn("❌ Очистить (все размеры)", "fs:clear"),
                 _btn("✅ Готово", "fs:done")])
    rows.append([_btn("← Назад", "m:filter")])
    return _kb(*rows)


# cate_code-ы для shortcut'ов по типу хода
WHEELED_SUBCATEGORIES = ["100105"]                    # 굴삭기타이어식 — колёсные
TRACKED_SUBCATEGORIES = ["100100", "100101", "100102", "100103", "100104"]


def pick_regions(selected: list[str]) -> InlineKeyboardMarkup:
    """Multi-select: корейские регионы."""
    selected_set = set(selected)
    rows: list[list[InlineKeyboardButton]] = []
    for i in range(0, len(REGIONS), 2):
        row = []
        for kr, ru in REGIONS[i:i+2]:
            mark = "☑️" if kr in selected_set else "▫️"
            row.append(_btn(f"{mark} {ru}", f"fr:t:{kr}"))
        rows.append(row)
    rows.append([_btn("❌ Очистить (любой)", "fr:clear"),
                 _btn("✅ Готово", "fr:done")])
    rows.append([_btn("← Назад", "m:filter")])
    return _kb(*rows)


def pick_grade(selected: int | None) -> InlineKeyboardMarkup:
    """Single-select: минимальный грейд."""
    def mk(rank: int, label: str) -> InlineKeyboardButton:
        mark = "🔘" if selected == rank else "⚪"
        return _btn(f"{mark} {label}", f"fg:{rank}")
    return _kb(
        [_btn(("🔘" if selected is None else "⚪") + " Любой грейд", "fg:any")],
        [mk(4, "Не ниже A+급"), mk(3, "Не ниже A급")],
        [mk(2, "Не ниже B+급"), mk(1, "Не ниже B급")],
        [_btn("← Назад", "m:filter")],
    )


def pick_blacklist() -> InlineKeyboardMarkup:
    return _kb(
        [_btn("✏️ Ввести / изменить список", "fb:custom")],
        [_btn("❌ Очистить", "fb:clear")],
        [_btn("← Назад", "m:filter")],
    )


def pick_year(role: str) -> InlineKeyboardMarkup:
    """role = 'yf' (год от) или 'yt' (год до)"""
    years = [2015, 2018, 2020, 2022, 2023, 2024, 2025, 2026]
    rows: list[list[InlineKeyboardButton]] = [[_btn("❌ Любой", f"f{role}:any")]]
    for i in range(0, len(years), 4):
        rows.append([_btn(str(y), f"f{role}:{y}") for y in years[i:i+4]])
    rows.append([_btn("← Назад", "m:filter")])
    return _kb(*rows)


def pick_price() -> InlineKeyboardMarkup:
    """Экран максимальной цены (с переходом на минимум)."""
    presets = [3000, 5000, 10000, 15000, 20000, 30000]   # в 만원
    rows: list[list[InlineKeyboardButton]] = [
        [_btn("💰 МАКС. цена в 만원:", "m:noop")],
        [_btn("❌ Без ограничения", "fp:any")],
    ]
    for i in range(0, len(presets), 3):
        rows.append([_btn(f"≤ {p:,}", f"fp:{p}") for p in presets[i:i+3]])
    rows.append([_btn("✏️ Своё", "fp:custom"),
                 _btn("⬇️ Настроить МИН. цену", "fpmn:open")])
    rows.append([_btn("← Назад", "m:filter")])
    return _kb(*rows)


def pick_price_min() -> InlineKeyboardMarkup:
    presets = [500, 1000, 2000, 5000, 10000]
    rows: list[list[InlineKeyboardButton]] = [
        [_btn("💰 МИН. цена в 만원:", "m:noop")],
        [_btn("❌ Без ограничения", "fpmn:any")],
    ]
    for i in range(0, len(presets), 3):
        rows.append([_btn(f"≥ {p:,}", f"fpmn:{p}") for p in presets[i:i+3]])
    rows.append([_btn("✏️ Своё", "fpmn:custom"),
                 _btn("⬆️ К МАКС. цене", "f:edit:p")])
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
    if not f.manufacturers:
        return "Любой"
    if len(f.manufacturers) == 1:
        kr = f.manufacturers[0]
        return next((en for k, en in MANUFACTURERS if k == kr), kr)
    return f"{len(f.manufacturers)} брендов"


def _short_subs(f: UserFilter) -> str:
    if not f.subcategories:
        return "Размер: любой"
    if len(f.subcategories) == 1:
        c = f.subcategories[0]
        return EXCAVATOR_SUBCATEGORIES.get(c, (c, c))[1]
    return f"{len(f.subcategories)} размеров"


def _short_region(f: UserFilter) -> str:
    if not f.regions:
        return "Регион: любой"
    if len(f.regions) == 1:
        kr = f.regions[0]
        return next((ru for k, ru in REGIONS if k == kr), kr)
    return f"{len(f.regions)} регионов"


def _short_grade(f: UserFilter) -> str:
    if not f.min_grade:
        return "Любой грейд"
    return f"≥ {grade_label(f.min_grade)}"


def _short_blacklist(f: UserFilter) -> str:
    if not f.blacklist_keywords:
        return "Без исключений"
    if len(f.blacklist_keywords) == 1:
        kw = f.blacklist_keywords[0]
        return kw if len(kw) <= 14 else kw[:13] + "…"
    return f"{len(f.blacklist_keywords)} слов"


def _short_year(f: UserFilter) -> str:
    if not f.year_from and not f.year_to:
        return "Любой год"
    a = str(f.year_from) if f.year_from else "—"
    b = str(f.year_to) if f.year_to else "—"
    return f"{a}…{b}"


def _short_price(f: UserFilter) -> str:
    if not f.price_max_won and not f.price_min_won:
        return "Любая цена"
    a = f"{f.price_min_won // 10000}" if f.price_min_won else "0"
    b = f"{f.price_max_won // 10000}" if f.price_max_won else "∞"
    return f"{a}–{b} 만원".replace(",", " ")


def _short_hours(f: UserFilter) -> str:
    if f.hours_max is None:
        return "Любые часы"
    return f"≤ {f.hours_max:,} ч".replace(",", " ")


def _short_keyword(f: UserFilter) -> str:
    if not f.keyword:
        return "Без слова"
    kw = f.keyword if len(f.keyword) <= 15 else f.keyword[:14] + "…"
    return f'"{kw}"'
