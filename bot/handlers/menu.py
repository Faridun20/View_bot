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
    price = State()       # МАКС цена
    price_min = State()
    hours = State()
    keyword = State()
    blacklist = State()


@router.message(Command("cancel"))
async def cmd_cancel(msg: Message, state: FSMContext) -> None:
    """Выйти из любого активного FSM-состояния."""
    current = await state.get_state()
    await state.clear()
    if current:
        f = init_db(config.DB_PATH).get_filter(msg.chat.id)
        await msg.answer("Ввод отменён.", reply_markup=keyboards.filter_menu(f))
    else:
        await msg.answer("Нечего отменять — вы не вводите данных.")


# ---------- /menu ----------------------------------------------------------

@router.message(Command("menu"))
async def cmd_menu(msg: Message, state: FSMContext) -> None:
    await state.clear()
    db = init_db(config.DB_PATH)
    db.upsert_user(msg.chat.id, msg.from_user.username if msg.from_user else None)
    auto_on = db.is_active(msg.chat.id)
    text = _main_text(db, msg.chat.id, auto_on)
    await msg.answer(text, parse_mode="HTML",
                     reply_markup=keyboards.main_menu(auto_on))


def _main_text(db, chat_id: int, auto_on: bool) -> str:
    """Главное меню — статус, сводка фильтра, счётчик избранного."""
    f = db.get_filter(chat_id)
    favs_n = db.count_favorites(chat_id)

    # Авто-уведомления
    if auto_on:
        auto_line = (
            f"🔔 <b>Авто-уведомления ВКЛ</b> — каждые "
            f"{config.MONITOR_INTERVAL_MINUTES} мин"
        )
    else:
        auto_line = "🔕 <b>Авто-уведомления ВЫКЛ</b>"

    # Сводка фильтра одной строкой
    if f.is_empty():
        filter_line = "🎯 <b>Фильтр пуст</b> — придут все новые экскаваторы"
    else:
        # Считаем сколько параметров реально задано
        active = [x for x in [
            f.manufacturers, f.subcategories, f.regions, f.min_grade,
            f.blacklist_keywords, f.blacklist_sellers,
            f.year_from, f.year_to,
            f.price_min_won, f.price_max_won,
            f.hours_max, f.skip_no_hours, f.require_photo, f.keyword,
        ] if x]
        filter_line = f"🎯 <b>Фильтр активен</b> — {len(active)} параметр(а/ов)"

    favs_line = f"🔖 <b>Избранное:</b> {favs_n} лотов" if favs_n else "🔖 <i>Нет избранного</i>"

    return (
        "<b>📋 Главное меню</b>\n\n"
        f"{auto_line}\n"
        f"{filter_line}\n"
        f"{favs_line}"
    )


def _filter_text(f: UserFilter) -> str:
    if f.is_empty():
        body = "<i>Фильтр пустой — будут приходить все новые экскаваторы.</i>"
    else:
        rows = [
            f"📏 {keyboards._short_subs(f)}",
            f"🏭 {keyboards._short_mfr(f)}",
            f"📍 {keyboards._short_region(f)}",
            f"🏆 {keyboards._short_grade(f)}",
            f"📅 {keyboards._short_year(f)}",
            f"💰 {keyboards._short_price(f)}",
            f"⏱ {keyboards._short_hours(f)}"
            + ("  🚫 без часов" if f.skip_no_hours else ""),
            f"🔍 {keyboards._short_keyword(f)}",
            f"🚫 {keyboards._short_blacklist(f)}",
            ("📷 Только с фото" if f.require_photo else "🖼 Любые (с/без фото)"),
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
    db = init_db(config.DB_PATH)
    auto_on = db.is_active(cb.message.chat.id)
    await _edit(cb, _main_text(db, cb.message.chat.id, auto_on),
                keyboards.main_menu(auto_on))
    await cb.answer()


@router.callback_query(F.data == "m:auto:t")
async def cb_main_auto_toggle(cb: CallbackQuery) -> None:
    db = init_db(config.DB_PATH)
    new_active = not db.is_active(cb.message.chat.id)
    db.set_active(cb.message.chat.id, new_active)
    await _edit(cb, _main_text(db, cb.message.chat.id, new_active),
                keyboards.main_menu(new_active))
    await cb.answer(
        "Авто-уведомления включены 🔔" if new_active
        else "Авто-уведомления выключены 🔕",
        show_alert=False,
    )


@router.callback_query(F.data == "m:favs")
async def cb_main_favs(cb: CallbackQuery) -> None:
    """Кнопка «Избранное» в главном меню — показывает избранные лоты."""
    await cb.answer("Открываю избранное…")
    from bot.handlers.favorites import show_favorites
    await show_favorites(cb.bot, cb.message.chat.id)


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
    f = init_db(config.DB_PATH).get_filter(cb.message.chat.id)
    await _edit(
        cb,
        "<b>🏭 Производитель</b>\n\nМожно выбрать <b>несколько</b>. "
        "Нажмите чекбоксы и затем «Готово».",
        keyboards.pick_manufacturer(f.manufacturers),
    )
    await cb.answer()


@router.callback_query(F.data == "f:edit:s")
async def cb_edit_subs(cb: CallbackQuery) -> None:
    f = init_db(config.DB_PATH).get_filter(cb.message.chat.id)
    await _edit(
        cb,
        "<b>📏 Размер экскаватора</b>\n\nВыберите одну или несколько подкатегорий. "
        "Пусто = все размеры.",
        keyboards.pick_subcategories(f.subcategories),
    )
    await cb.answer()


@router.callback_query(F.data == "f:edit:r")
async def cb_edit_region(cb: CallbackQuery) -> None:
    f = init_db(config.DB_PATH).get_filter(cb.message.chat.id)
    await _edit(
        cb,
        "<b>📍 Регион</b>\n\nКорейские провинции и города-метрополии. "
        "Можно выбрать несколько.",
        keyboards.pick_regions(f.regions),
    )
    await cb.answer()


@router.callback_query(F.data == "f:edit:g")
async def cb_edit_grade(cb: CallbackQuery) -> None:
    f = init_db(config.DB_PATH).get_filter(cb.message.chat.id)
    await _edit(
        cb,
        "<b>🏆 Минимальный грейд</b>\n\n"
        "Грейд состояния указан в каждой карточке (상태). "
        "A+급 — лучшее, B급 — приемлемое.",
        keyboards.pick_grade(f.min_grade),
    )
    await cb.answer()


@router.callback_query(F.data == "f:edit:b")
async def cb_edit_blacklist(cb: CallbackQuery) -> None:
    await _edit(
        cb,
        "<b>🚫 Чёрный список ключевых слов</b>\n\n"
        "Если в названии или описании встречается слово из списка — лот не придёт.\n\n"
        "Примеры: <code>수리품</code> (восстановленный), "
        "<code>사고차</code> (ДТП), <code>급매</code> (срочно)",
        keyboards.pick_blacklist(),
    )
    await cb.answer()


@router.callback_query(F.data == "f:edit:y")
async def cb_edit_year(cb: CallbackQuery) -> None:
    await _edit(cb, "<b>📅 Год выпуска ОТ</b>", keyboards.pick_year("yf"))
    await cb.answer()


@router.callback_query(F.data == "f:edit:p")
async def cb_edit_price(cb: CallbackQuery) -> None:
    await _edit(
        cb,
        "<b>💰 Цена</b>\n\nв 만원 (10 000 ВОН).\n"
        "Например 15 000 = ~150 млн ВОН ≈ $110 000.",
        keyboards.pick_price(),
    )
    await cb.answer()


@router.callback_query(F.data == "f:edit:h")
async def cb_edit_hours(cb: CallbackQuery) -> None:
    await _edit(
        cb,
        "<b>⏱ Максимальные моточасы</b>\n\n"
        "Если включить «не присылать без часов» в главном экране фильтра — "
        "лоты с пустым полем 운행 тоже отсекутся.",
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
    """Multi-select производителей: fm:t:<кр> | fm:clear | fm:done"""
    parts = cb.data.split(":")
    db = init_db(config.DB_PATH)
    f = db.get_filter(cb.message.chat.id)

    action = parts[1]
    if action == "t":
        kr = parts[2]
        if kr in f.manufacturers:
            f.manufacturers = [m for m in f.manufacturers if m != kr]
        else:
            f.manufacturers = list(f.manufacturers) + [kr]
        db.set_filter(f)
        await _edit(cb, "<b>🏭 Производитель</b>",
                    keyboards.pick_manufacturer(f.manufacturers))
        await cb.answer()
        return
    if action == "clear":
        f.manufacturers = []
        db.set_filter(f)
        await _edit(cb, "<b>🏭 Производитель</b>",
                    keyboards.pick_manufacturer([]))
        await cb.answer("Очищено")
        return
    if action == "done":
        await _edit(cb, _filter_text(f), keyboards.filter_menu(f))
        await cb.answer("Сохранено")
        return


@router.callback_query(F.data.startswith("fs:"))
async def cb_pick_subs(cb: CallbackQuery) -> None:
    """Multi-select подкатегорий-размеров.

    Callback'и: fs:t:<cate> | fs:clear | fs:done |
                fs:chassis:wheeled | fs:chassis:tracked
    """
    parts = cb.data.split(":")
    db = init_db(config.DB_PATH)
    f = db.get_filter(cb.message.chat.id)
    action = parts[1]
    if action == "t":
        cate = parts[2]
        if cate in f.subcategories:
            f.subcategories = [c for c in f.subcategories if c != cate]
        else:
            f.subcategories = list(f.subcategories) + [cate]
        db.set_filter(f)
        await _edit(cb, "<b>📏 Размер экскаватора</b>",
                    keyboards.pick_subcategories(f.subcategories))
        await cb.answer()
        return
    if action == "clear":
        f.subcategories = []
        db.set_filter(f)
        await _edit(cb, "<b>📏 Размер экскаватора</b>",
                    keyboards.pick_subcategories([]))
        await cb.answer("Очищено")
        return
    if action == "chassis":
        # Shortcut: переписать набор подкатегорий по типу хода
        kind = parts[2]
        if kind == "wheeled":
            f.subcategories = list(keyboards.WHEELED_SUBCATEGORIES)
            note = "🛞 Только колёсные"
        elif kind == "tracked":
            f.subcategories = list(keyboards.TRACKED_SUBCATEGORIES)
            note = "🦂 Только гусеничные"
        else:
            await cb.answer()
            return
        db.set_filter(f)
        await _edit(cb, f"<b>📏 Размер экскаватора</b>\n\n{note} ✅",
                    keyboards.pick_subcategories(f.subcategories))
        await cb.answer(note)
        return
    if action == "done":
        await _edit(cb, _filter_text(f), keyboards.filter_menu(f))
        await cb.answer("Сохранено")
        return


@router.callback_query(F.data.startswith("fr:"))
async def cb_pick_region(cb: CallbackQuery) -> None:
    """Multi-select регионов: fr:t:<key> | fr:clear | fr:done"""
    parts = cb.data.split(":")
    db = init_db(config.DB_PATH)
    f = db.get_filter(cb.message.chat.id)
    action = parts[1]
    if action == "t":
        key = parts[2]
        if key in f.regions:
            f.regions = [r for r in f.regions if r != key]
        else:
            f.regions = list(f.regions) + [key]
        db.set_filter(f)
        await _edit(cb, "<b>📍 Регион</b>", keyboards.pick_regions(f.regions))
        await cb.answer()
        return
    if action == "clear":
        f.regions = []
        db.set_filter(f)
        await _edit(cb, "<b>📍 Регион</b>", keyboards.pick_regions([]))
        await cb.answer("Очищено")
        return
    if action == "done":
        await _edit(cb, _filter_text(f), keyboards.filter_menu(f))
        await cb.answer("Сохранено")
        return


@router.callback_query(F.data.startswith("fg:"))
async def cb_pick_grade(cb: CallbackQuery) -> None:
    """Single-select грейда: fg:<1..4> | fg:any"""
    val = cb.data.split(":", 1)[1]
    db = init_db(config.DB_PATH)
    f = db.get_filter(cb.message.chat.id)
    f.min_grade = None if val == "any" else int(val)
    db.set_filter(f)
    await _edit(cb, _filter_text(f), keyboards.filter_menu(f))
    await cb.answer("Сохранено")


@router.callback_query(F.data.startswith("fb:"))
async def cb_pick_blacklist(cb: CallbackQuery, state: FSMContext) -> None:
    """fb:custom | fb:clear"""
    val = cb.data.split(":", 1)[1]
    db = init_db(config.DB_PATH)
    f = db.get_filter(cb.message.chat.id)
    if val == "custom":
        await state.set_state(MenuInput.blacklist)
        current = ", ".join(f.blacklist_keywords) if f.blacklist_keywords else "(пусто)"
        await _edit(
            cb,
            "<b>🚫 Чёрный список</b>\n\n"
            f"Текущий список: <code>{current}</code>\n\n"
            "Введите слова через запятую — они заменят текущий список.\n"
            "Например: <code>수리품, 사고차, 부품용</code>",
            keyboards.back_to_filter(),
        )
        await cb.answer()
        return
    if val == "clear":
        f.blacklist_keywords = []
        db.set_filter(f)
        await _edit(cb, _filter_text(f), keyboards.filter_menu(f))
        await cb.answer("Очищено")
        return


@router.callback_query(F.data == "fnoh:t")
async def cb_toggle_no_hours(cb: CallbackQuery) -> None:
    db = init_db(config.DB_PATH)
    f = db.get_filter(cb.message.chat.id)
    f.skip_no_hours = not f.skip_no_hours
    db.set_filter(f)
    await _edit(cb, _filter_text(f), keyboards.filter_menu(f))
    await cb.answer(
        "Лоты без часов будут пропускаться" if f.skip_no_hours
        else "Лоты без часов будут приходить"
    )


@router.callback_query(F.data == "fph:t")
async def cb_toggle_require_photo(cb: CallbackQuery) -> None:
    db = init_db(config.DB_PATH)
    f = db.get_filter(cb.message.chat.id)
    f.require_photo = not f.require_photo
    db.set_filter(f)
    await _edit(cb, _filter_text(f), keyboards.filter_menu(f))
    await cb.answer(
        "Только лоты с фото 📷" if f.require_photo
        else "Любые лоты (с/без фото) 🖼"
    )


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
    """МАКС цена: fp:<манвон> | fp:any | fp:custom"""
    val = cb.data.split(":", 1)[1]
    db = init_db(config.DB_PATH)
    f = db.get_filter(cb.message.chat.id)
    if val == "custom":
        await state.set_state(MenuInput.price)
        await _edit(
            cb,
            "<b>💰 Своя МАКС. цена</b>\n\n"
            "Введите число в 만원 (например <code>12500</code>).\n"
            "Или нажмите «Назад».",
            keyboards.back_to_filter(),
        )
        await cb.answer()
        return
    f.price_max_won = None if val == "any" else int(val) * 10_000
    db.set_filter(f)
    await _edit(cb, _filter_text(f), keyboards.filter_menu(f))
    await cb.answer("Сохранено")


@router.callback_query(F.data.startswith("fpmn:"))
async def cb_pick_price_min(cb: CallbackQuery, state: FSMContext) -> None:
    """МИН цена: fpmn:open (открыть экран) | fpmn:<манвон> | fpmn:any | fpmn:custom"""
    val = cb.data.split(":", 1)[1]
    if val == "open":
        await _edit(
            cb,
            "<b>💰 Минимальная цена</b>\n\n"
            "Отсекает откровенно копеечные лоты.",
            keyboards.pick_price_min(),
        )
        await cb.answer()
        return

    db = init_db(config.DB_PATH)
    f = db.get_filter(cb.message.chat.id)
    if val == "custom":
        await state.set_state(MenuInput.price_min)
        await _edit(
            cb,
            "<b>💰 Своя МИН. цена</b>\n\n"
            "Введите число в 만원 (например <code>2000</code>).",
            keyboards.back_to_filter(),
        )
        await cb.answer()
        return
    f.price_min_won = None if val == "any" else int(val) * 10_000
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

@router.message(MenuInput.price, ~F.text.startswith("/"))
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


@router.message(MenuInput.price_min, ~F.text.startswith("/"))
async def msg_input_price_min(msg: Message, state: FSMContext) -> None:
    digits = "".join(c for c in (msg.text or "") if c.isdigit())
    if not digits:
        await msg.answer("Нужно положительное число (в 만원).")
        return
    db = init_db(config.DB_PATH)
    f = db.get_filter(msg.chat.id)
    f.price_min_won = int(digits) * 10_000
    db.set_filter(f)
    await state.clear()
    await msg.answer(_filter_text(f), parse_mode="HTML",
                     reply_markup=keyboards.filter_menu(f))


@router.message(MenuInput.blacklist, ~F.text.startswith("/"))
async def msg_input_blacklist(msg: Message, state: FSMContext) -> None:
    text = (msg.text or "").strip()
    if not text:
        await msg.answer("Введите слова через запятую или нажмите «Назад».")
        return
    items = [t.strip() for t in text.split(",") if t.strip()]
    db = init_db(config.DB_PATH)
    f = db.get_filter(msg.chat.id)
    f.blacklist_keywords = items
    db.set_filter(f)
    await state.clear()
    await msg.answer(_filter_text(f), parse_mode="HTML",
                     reply_markup=keyboards.filter_menu(f))


@router.message(MenuInput.hours, ~F.text.startswith("/"))
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


@router.message(MenuInput.keyword, ~F.text.startswith("/"))
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
