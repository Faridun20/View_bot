"""Команда /menu и обработчики inline-клавиатур.

Главная навигация: m:main / m:search / m:filter / m:help / m:noop
В подменю фильтра — простые callback-маркеры, см. bot/keyboards.py.
Для произвольного ввода (цена, моточасы, ключевое слово) используется
маленькая FSM-группа MenuInput.
"""
from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from bot import config, keyboards
from bot.handlers.search import do_search
from bot.handlers.start import HELP_TEXT
from bot.storage import init_db
from bot.storage.db import UserFilter

logger = logging.getLogger(__name__)
router = Router(name="menu")


class MenuInput(StatesGroup):
    price = State()
    hours = State()
    keyword = State()


# ---------- /menu ----------------------------------------------------------

@router.message(Command("menu"))
async def cmd_menu(msg: Message, state: FSMContext) -> None:
    await state.clear()
    db = init_db(config.DB_PATH)
    db.upsert_user(msg.chat.id, msg.from_user.username if msg.from_user else None)
    await msg.answer(_main_text(), parse_mode="HTML",
                     reply_markup=keyboards.main_menu())


def _main_text() -> str:
    return (
        "<b>📋 Главное меню</b>\n\n"
        "🔍 <b>Поиск</b> — прислать N свежих лотов прямо сейчас\n"
        "⚙️ <b>Фильтр</b> — настроить, что вам интересно\n"
        "❓ <b>Помощь</b> — список всех команд"
    )


def _filter_text(f: UserFilter) -> str:
    if f.is_empty():
        body = "<i>Фильтр пустой — будут приходить все новые экскаваторы.</i>"
    else:
        rows = [
            f"🏭 {keyboards._short_mfr(f)}",
            f"📅 {keyboards._short_year(f)}",
            f"💰 {keyboards._short_price(f)}",
            f"⏱ {keyboards._short_hours(f)}",
            f"🔍 {keyboards._short_keyword(f)}",
        ]
        body = "\n".join(rows)
    return f"<b>⚙️ Ваш фильтр</b>\n\n{body}\n\nТапните по строке, чтобы изменить:"


# ---------- навигация по экранам -------------------------------------------

@router.callback_query(F.data == "m:noop")
async def cb_noop(cb: CallbackQuery) -> None:
    """Подпись-заголовок в меню поиска — клик ничего не делает."""
    await cb.answer()


@router.callback_query(F.data == "m:main")
async def cb_main(cb: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await _edit(cb, _main_text(), keyboards.main_menu())
    await cb.answer()


@router.callback_query(F.data == "m:search")
async def cb_search_menu(cb: CallbackQuery) -> None:
    await _edit(
        cb,
        "<b>🔍 Поиск</b>\n\nСколько лотов прислать?",
        keyboards.search_menu(),
    )
    await cb.answer()


@router.callback_query(F.data == "m:filter")
async def cb_filter_menu(cb: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    f = init_db(config.DB_PATH).get_filter(cb.message.chat.id)
    await _edit(cb, _filter_text(f), keyboards.filter_menu(f))
    await cb.answer()


@router.callback_query(F.data == "m:help")
async def cb_help(cb: CallbackQuery) -> None:
    await _edit(cb, HELP_TEXT, keyboards.back_to_main())
    await cb.answer()


# ---------- search ---------------------------------------------------------

@router.callback_query(F.data.startswith("s:"))
async def cb_search_run(cb: CallbackQuery) -> None:
    parts = cb.data.split(":")
    # s:5 / s:10 / s:20 / s:all:5 / s:forget
    if parts[1] == "forget":
        removed = init_db(config.DB_PATH).clear_sent(cb.message.chat.id)
        await cb.answer(f"♻️ Очищено: {removed}", show_alert=True)
        return
    if parts[1] == "all":
        show_all = True
        n = int(parts[2])
    else:
        show_all = False
        n = int(parts[1])
    await cb.answer(f"Ищу {n} лотов…")
    # do_search сам шлёт сообщения; меню остаётся выше, ничего не дёргаем
    await do_search(cb.bot, cb.message.chat.id, n=n, show_all=show_all)


# ---------- filter: главный экран ------------------------------------------

@router.callback_query(F.data == "f:reset")
async def cb_filter_reset(cb: CallbackQuery) -> None:
    init_db(config.DB_PATH).reset_filter(cb.message.chat.id)
    f = init_db(config.DB_PATH).get_filter(cb.message.chat.id)
    await _edit(cb, _filter_text(f), keyboards.filter_menu(f))
    await cb.answer("Сброшено")


@router.callback_query(F.data == "f:edit:m")
async def cb_edit_mfr(cb: CallbackQuery) -> None:
    await _edit(cb, "<b>🏭 Производитель</b>", keyboards.pick_manufacturer())
    await cb.answer()


@router.callback_query(F.data == "f:edit:y")
async def cb_edit_year(cb: CallbackQuery) -> None:
    await _edit(cb, "<b>📅 Год выпуска ОТ</b>", keyboards.pick_year("yf"))
    await cb.answer()


@router.callback_query(F.data == "f:edit:p")
async def cb_edit_price(cb: CallbackQuery) -> None:
    await _edit(
        cb,
        "<b>💰 Максимальная цена</b>\n\nв 만원 (10 000 ВОН).\n"
        "Например 15 000 = ~150 млн ВОН ≈ $110 000.",
        keyboards.pick_price(),
    )
    await cb.answer()


@router.callback_query(F.data == "f:edit:h")
async def cb_edit_hours(cb: CallbackQuery) -> None:
    await _edit(
        cb,
        "<b>⏱ Максимальные моточасы</b>\n\n"
        "Лоты без указанных моточасов <b>всё равно</b> придут (с пометкой).",
        keyboards.pick_hours(),
    )
    await cb.answer()


@router.callback_query(F.data == "f:edit:k")
async def cb_edit_kw(cb: CallbackQuery) -> None:
    await _edit(
        cb,
        "<b>🔍 Ключевое слово</b>\n\n"
        "Поиск подстроки в названии модели и описании.",
        keyboards.pick_keyword(),
    )
    await cb.answer()


# ---------- filter: выбор значения -----------------------------------------

@router.callback_query(F.data.startswith("fm:"))
async def cb_pick_mfr(cb: CallbackQuery) -> None:
    val = cb.data.split(":", 1)[1]
    db = init_db(config.DB_PATH)
    f = db.get_filter(cb.message.chat.id)
    f.manufacturer = None if val == "any" else val
    db.set_filter(f)
    await _edit(cb, _filter_text(f), keyboards.filter_menu(f))
    await cb.answer("Сохранено")


@router.callback_query(F.data.startswith("fyf:"))
async def cb_pick_year_from(cb: CallbackQuery) -> None:
    val = cb.data.split(":", 1)[1]
    db = init_db(config.DB_PATH)
    f = db.get_filter(cb.message.chat.id)
    f.year_from = None if val == "any" else int(val)
    db.set_filter(f)
    # После выбора «года ОТ» — сразу предложить «год ДО»
    await _edit(cb, "<b>📅 Год выпуска ДО</b>", keyboards.pick_year("yt"))
    await cb.answer("Сохранено")


@router.callback_query(F.data.startswith("fyt:"))
async def cb_pick_year_to(cb: CallbackQuery) -> None:
    val = cb.data.split(":", 1)[1]
    db = init_db(config.DB_PATH)
    f = db.get_filter(cb.message.chat.id)
    f.year_to = None if val == "any" else int(val)
    db.set_filter(f)
    await _edit(cb, _filter_text(f), keyboards.filter_menu(f))
    await cb.answer("Сохранено")


@router.callback_query(F.data.startswith("fp:"))
async def cb_pick_price(cb: CallbackQuery, state: FSMContext) -> None:
    val = cb.data.split(":", 1)[1]
    db = init_db(config.DB_PATH)
    f = db.get_filter(cb.message.chat.id)
    if val == "custom":
        await state.set_state(MenuInput.price)
        await _edit(
            cb,
            "<b>💰 Своя цена</b>\n\n"
            "Введите число в 만원 (например <code>12500</code>).\n"
            "Или нажмите «Назад» для отмены.",
            keyboards.back_to_filter(),
        )
        await cb.answer()
        return
    f.price_max_won = None if val == "any" else int(val) * 10_000
    db.set_filter(f)
    await _edit(cb, _filter_text(f), keyboards.filter_menu(f))
    await cb.answer("Сохранено")


@router.callback_query(F.data.startswith("fh:"))
async def cb_pick_hours(cb: CallbackQuery, state: FSMContext) -> None:
    val = cb.data.split(":", 1)[1]
    db = init_db(config.DB_PATH)
    f = db.get_filter(cb.message.chat.id)
    if val == "custom":
        await state.set_state(MenuInput.hours)
        await _edit(
            cb,
            "<b>⏱ Свои моточасы</b>\n\n"
            "Введите число (например <code>7500</code>).",
            keyboards.back_to_filter(),
        )
        await cb.answer()
        return
    f.hours_max = None if val == "any" else int(val)
    db.set_filter(f)
    await _edit(cb, _filter_text(f), keyboards.filter_menu(f))
    await cb.answer("Сохранено")


@router.callback_query(F.data.startswith("fk:"))
async def cb_pick_keyword(cb: CallbackQuery, state: FSMContext) -> None:
    val = cb.data.split(":", 1)[1]
    db = init_db(config.DB_PATH)
    f = db.get_filter(cb.message.chat.id)
    if val == "custom":
        await state.set_state(MenuInput.keyword)
        await _edit(
            cb,
            "<b>🔍 Ключевое слово</b>\n\n"
            "Введите подстроку — латиницей или корейским "
            "(например <code>DX380</code>, <code>볼보</code>).",
            keyboards.back_to_filter(),
        )
        await cb.answer()
        return
    if val == "clear":
        f.keyword = None
        db.set_filter(f)
        await _edit(cb, _filter_text(f), keyboards.filter_menu(f))
        await cb.answer("Очищено")


# ---------- ввод произвольных значений (после "Своё значение") -------------

@router.message(MenuInput.price)
async def msg_input_price(msg: Message, state: FSMContext) -> None:
    digits = "".join(c for c in (msg.text or "") if c.isdigit())
    if not digits:
        await msg.answer("Нужно положительное число (в 만원).")
        return
    db = init_db(config.DB_PATH)
    f = db.get_filter(msg.chat.id)
    f.price_max_won = int(digits) * 10_000
    db.set_filter(f)
    await state.clear()
    await msg.answer(_filter_text(f), parse_mode="HTML",
                     reply_markup=keyboards.filter_menu(f))


@router.message(MenuInput.hours)
async def msg_input_hours(msg: Message, state: FSMContext) -> None:
    digits = "".join(c for c in (msg.text or "") if c.isdigit())
    if not digits:
        await msg.answer("Нужно число моточасов.")
        return
    db = init_db(config.DB_PATH)
    f = db.get_filter(msg.chat.id)
    f.hours_max = int(digits)
    db.set_filter(f)
    await state.clear()
    await msg.answer(_filter_text(f), parse_mode="HTML",
                     reply_markup=keyboards.filter_menu(f))


@router.message(MenuInput.keyword)
async def msg_input_keyword(msg: Message, state: FSMContext) -> None:
    text = (msg.text or "").strip()
    if not text:
        await msg.answer("Введите хоть что-то, или нажмите «Назад».")
        return
    db = init_db(config.DB_PATH)
    f = db.get_filter(msg.chat.id)
    f.keyword = text
    db.set_filter(f)
    await state.clear()
    await msg.answer(_filter_text(f), parse_mode="HTML",
                     reply_markup=keyboards.filter_menu(f))


# ---------- helpers --------------------------------------------------------

async def _edit(cb: CallbackQuery, text: str, kb) -> None:
    """Отредактировать сообщение меню; если Telegram ругнётся (одинаковый
    контент) — проглатываем ошибку, она не страшная."""
    try:
        await cb.message.edit_text(text, parse_mode="HTML", reply_markup=kb,
                                   disable_web_page_preview=True)
    except TelegramAPIError:
        # Если меню было прислано как send_photo (например, после карточки) —
        # просто шлём новое сообщение.
        await cb.message.answer(text, parse_mode="HTML", reply_markup=kb,
                                disable_web_page_preview=True)
