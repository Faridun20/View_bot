"""Команды настройки фильтра подписки: /filter (FSM), /myfilter, /reset."""
from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    KeyboardButton, Message, ReplyKeyboardMarkup, ReplyKeyboardRemove,
)

from bot import config
from bot.storage import init_db
from bot.storage.db import UserFilter

logger = logging.getLogger(__name__)
router = Router(name="filters")


# Корейское название производителя → читаемая подпись.
# Левая часть (key) — это exactly то, что приходит в item.manufacturer.
MANUFACTURERS = [
    ("현대",       "Hyundai"),
    ("대우",       "Daewoo"),
    ("두산디벨론", "Doosan / Develon"),
    ("삼성",       "Samsung"),
    ("볼보",       "Volvo"),
    ("한라",       "Hanwha / Halla"),
    ("코마스",     "Komatsu"),
    ("히타치",     "Hitachi"),
    ("코벨코",     "Kobelco"),
    ("캐타필라",   "Caterpillar"),
    ("기타",       "Прочие"),
]

SKIP = "— пропустить —"
ANY = "— любой —"


class FilterDialog(StatesGroup):
    manufacturer = State()
    year_from = State()
    year_to = State()
    price_max = State()
    hours_max = State()
    keyword = State()


def _kb(*rows: list[str]) -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=c) for c in row] for row in rows],
        resize_keyboard=True, one_time_keyboard=True,
    )


def _parse_int(text: str) -> int | None:
    digits = "".join(c for c in text if c.isdigit())
    return int(digits) if digits else None


# ---------- /myfilter ------------------------------------------------------

def _describe(f: UserFilter) -> str:
    if f.is_empty():
        return "<i>Фильтр не задан — будут приходить все новые лоты в категории «Экскаваторы».</i>"
    rows = []
    if f.manufacturers:
        labels = []
        for m in f.manufacturers:
            en = next((en for kr, en in MANUFACTURERS if kr == m), m)
            labels.append(f"{en} ({m})")
        rows.append(f"🏭 Производитель: <b>{', '.join(labels)}</b>")
    if f.subcategories:
        from bot.scraper.models import EXCAVATOR_SUBCATEGORIES as _SUBS
        names = [_SUBS[c][1] for c in f.subcategories if c in _SUBS]
        rows.append(f"📏 Размер: <b>{', '.join(names)}</b>")
    if f.regions:
        from bot.scraper.models import REGION_LABELS
        labels = [f"{REGION_LABELS.get(r, r)}" for r in f.regions]
        rows.append(f"📍 Регион: <b>{', '.join(labels)}</b>")
    if f.min_grade:
        from bot.scraper.models import grade_label
        rows.append(f"🏆 Мин. грейд: <b>{grade_label(f.min_grade)}</b>")
    if f.year_from or f.year_to:
        a = f.year_from or "—"
        b = f.year_to or "—"
        rows.append(f"📅 Год: <b>{a}…{b}</b>")
    if f.price_min_won or f.price_max_won:
        a = f"{f.price_min_won // 10000} 만원" if f.price_min_won else "—"
        b = f"{f.price_max_won // 10000} 만원" if f.price_max_won else "—"
        rows.append(f"💰 Цена: <b>{a}…{b}</b>".replace(",", " "))
    if f.hours_max is not None:
        rows.append(f"⏱ Моточасы ≤ <b>{f.hours_max:,}</b>".replace(",", " "))
    if f.skip_no_hours:
        rows.append("🚫 Лоты без моточасов пропускаются")
    if f.require_photo:
        rows.append("📷 Только лоты с фото")
    if f.blacklist_keywords:
        rows.append(f"🚫 Исключить: <b>{', '.join(f.blacklist_keywords)}</b>")
    if f.keyword:
        rows.append(f"🔍 Ключевое слово: <b>{f.keyword}</b>")
    return "\n".join(rows)


@router.message(Command("myfilter"))
async def cmd_myfilter(msg: Message) -> None:
    db = init_db(config.DB_PATH)
    f = db.get_filter(msg.chat.id)
    await msg.answer(
        "<b>Ваш фильтр</b>\n\n" + _describe(f),
        parse_mode="HTML",
    )


@router.message(Command("reset"))
async def cmd_reset(msg: Message) -> None:
    db = init_db(config.DB_PATH)
    db.reset_filter(msg.chat.id)
    await msg.answer(
        "♻️ Фильтр сброшен — будут приходить все новые лоты.",
        reply_markup=ReplyKeyboardRemove(),
    )


# ---------- /filter (FSM) --------------------------------------------------

@router.message(Command("filter"))
async def cmd_filter_start(msg: Message, state: FSMContext) -> None:
    db = init_db(config.DB_PATH)
    db.upsert_user(msg.chat.id, msg.from_user.username if msg.from_user else None)

    await state.clear()
    await state.set_state(FilterDialog.manufacturer)
    # Раскладываем кнопки производителей по 2 в ряд + "— любой —"
    rows: list[list[str]] = []
    for i in range(0, len(MANUFACTURERS), 2):
        row = [f"{en} ({kr})" for kr, en in MANUFACTURERS[i:i+2]]
        rows.append(row)
    rows.append([ANY])
    await msg.answer(
        "<b>Шаг 1/6 — производитель</b>\nВыберите кнопкой или напишите название.",
        reply_markup=_kb(*rows), parse_mode="HTML",
    )


@router.message(FilterDialog.manufacturer)
async def fsm_manufacturer(msg: Message, state: FSMContext) -> None:
    text = msg.text or ""
    if text == ANY:
        manufacturer = None
    else:
        # принимаем «Volvo (볼보)» и любое корейское слово напрямую
        manufacturer = None
        for kr, en in MANUFACTURERS:
            if kr in text or en.lower() in text.lower():
                manufacturer = kr
                break
        if manufacturer is None:
            manufacturer = text.strip() or None
    await state.update_data(manufacturer=manufacturer)

    await state.set_state(FilterDialog.year_from)
    await msg.answer(
        "<b>Шаг 2/6 — год выпуска ОТ</b>\nНапишите 4-значный год, или нажмите «пропустить».",
        reply_markup=_kb([SKIP]), parse_mode="HTML",
    )


@router.message(FilterDialog.year_from)
async def fsm_year_from(msg: Message, state: FSMContext) -> None:
    if msg.text == SKIP:
        await state.update_data(year_from=None)
    else:
        y = _parse_int(msg.text or "")
        if y and 1990 <= y <= 2100:
            await state.update_data(year_from=y)
        else:
            await msg.answer("Не похоже на год. Введите 4-значное число или «пропустить».")
            return
    await state.set_state(FilterDialog.year_to)
    await msg.answer(
        "<b>Шаг 3/6 — год выпуска ДО</b>",
        reply_markup=_kb([SKIP]), parse_mode="HTML",
    )


@router.message(FilterDialog.year_to)
async def fsm_year_to(msg: Message, state: FSMContext) -> None:
    if msg.text == SKIP:
        await state.update_data(year_to=None)
    else:
        y = _parse_int(msg.text or "")
        if y and 1990 <= y <= 2100:
            await state.update_data(year_to=y)
        else:
            await msg.answer("Не похоже на год. Введите 4-значное число или «пропустить».")
            return
    await state.set_state(FilterDialog.price_max)
    await msg.answer(
        "<b>Шаг 4/6 — максимальная цена в 만원</b>\n"
        "На сайте цены указаны в 만원 (10 000 ВОН).\n"
        "Например <code>10000</code> = 100 000 000 ВОН ≈ $73 000.\n"
        "Введите число или «пропустить».",
        reply_markup=_kb([SKIP]), parse_mode="HTML",
    )


@router.message(FilterDialog.price_max)
async def fsm_price_max(msg: Message, state: FSMContext) -> None:
    if msg.text == SKIP:
        await state.update_data(price_max_won=None)
    else:
        v = _parse_int(msg.text or "")
        if v is None or v <= 0:
            await msg.answer("Введите положительное число или «пропустить».")
            return
        await state.update_data(price_max_won=v * 10_000)
    await state.set_state(FilterDialog.hours_max)
    await msg.answer(
        "<b>Шаг 5/6 — максимальные моточасы</b>\n"
        "Лоты без указанных моточасов всё равно будут приходить (с пометкой).\n"
        "Введите число или «пропустить».",
        reply_markup=_kb([SKIP]), parse_mode="HTML",
    )


@router.message(FilterDialog.hours_max)
async def fsm_hours_max(msg: Message, state: FSMContext) -> None:
    if msg.text == SKIP:
        await state.update_data(hours_max=None)
    else:
        v = _parse_int(msg.text or "")
        if v is None or v < 0:
            await msg.answer("Введите неотрицательное число или «пропустить».")
            return
        await state.update_data(hours_max=v)
    await state.set_state(FilterDialog.keyword)
    await msg.answer(
        "<b>Шаг 6/6 — ключевое слово</b>\n"
        "Поиск подстроки в модели и описании (например <code>DX380</code>, <code>볼보</code>).",
        reply_markup=_kb([SKIP]), parse_mode="HTML",
    )


@router.message(FilterDialog.keyword)
async def fsm_keyword(msg: Message, state: FSMContext) -> None:
    if msg.text == SKIP:
        keyword = None
    else:
        keyword = (msg.text or "").strip() or None

    data = await state.get_data()
    mfr = data.get("manufacturer")
    f = UserFilter(
        chat_id=msg.chat.id,
        manufacturers=[mfr] if mfr else [],
        year_from=data.get("year_from"),
        year_to=data.get("year_to"),
        price_max_won=data.get("price_max_won"),
        hours_max=data.get("hours_max"),
        keyword=keyword,
    )
    db = init_db(config.DB_PATH)
    db.set_filter(f)
    await state.clear()
    await msg.answer(
        "✅ Фильтр сохранён:\n\n" + _describe(f),
        parse_mode="HTML", reply_markup=ReplyKeyboardRemove(),
    )
