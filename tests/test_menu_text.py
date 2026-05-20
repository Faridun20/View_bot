"""Тесты чистых текст-хелперов хендлеров (без aiogram runtime)."""
from __future__ import annotations

from bot.handlers.menu import _filter_text
from bot.handlers.search import _plural_lots
from bot.storage.db import UserFilter


def test_filter_text_empty():
    txt = _filter_text(UserFilter(chat_id=1))
    assert "пустой" in txt.lower()
    # У пустого фильтра не должно быть списка «Активные условия»
    assert "Активные условия" not in txt


def test_filter_text_lists_only_active():
    f = UserFilter(chat_id=1, manufacturers=["볼보"], hours_max=5000,
                   require_photo=True)
    txt = _filter_text(f)
    assert "Активные условия" in txt
    assert "Volvo" in txt          # _short_mfr маппит 볼보 → Volvo
    assert "5 000 ч" in txt or "5000" in txt
    assert "фото" in txt.lower()
    # Незаданные условия не перечисляем как пункты
    assert "Любой грейд" not in txt
    assert "Любой год" not in txt


def test_plural_lots():
    assert _plural_lots(1) == "лот"
    assert _plural_lots(2) == "лота"
    assert _plural_lots(3) == "лота"
    assert _plural_lots(5) == "лотов"
    assert _plural_lots(11) == "лотов"
    assert _plural_lots(21) == "лот"
    assert _plural_lots(112) == "лотов"
