"""Юнит-тесты слоя хранения."""
from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone

from bot.storage.db import UserFilter


def test_wal_mode(isolated_db):
    # Прямой запрос — какой journal_mode у БД
    from bot import config
    with sqlite3.connect(config.DB_PATH) as c:
        mode = c.execute("PRAGMA journal_mode").fetchone()[0]
    assert mode.lower() == "wal"


def test_users_active_lifecycle(isolated_db):
    db = isolated_db
    is_new = db.upsert_user(42, "alice")
    assert is_new is True                # первый раз — новый
    assert db.is_active(42)
    assert 42 in db.active_users()
    db.set_active(42, False)
    assert not db.is_active(42)
    assert 42 not in db.active_users()
    db.set_active(42, True)
    assert db.is_active(42)
    # upsert повторно — НЕ новый
    again = db.upsert_user(42, "alice2")
    assert again is False
    assert len(db.active_users()) == 1


def test_filter_roundtrip(isolated_db):
    db = isolated_db
    db.upsert_user(1, "u")
    f = UserFilter(
        chat_id=1,
        manufacturers=["볼보", "두산디벨론"],
        subcategories=["100100"],
        regions=["경기", "강원"],
        min_grade=3,
        blacklist_keywords=["수리품"],
        year_from=2020, year_to=2024,
        price_min_won=20_000_000, price_max_won=200_000_000,
        hours_max=8000,
        skip_no_hours=True, require_photo=True,
        keyword="DX",
    )
    db.set_filter(f)
    got = db.get_filter(1)
    assert got.manufacturers == ["볼보", "두산디벨론"]
    assert got.subcategories == ["100100"]
    assert got.regions == ["경기", "강원"]
    assert got.min_grade == 3
    assert got.blacklist_keywords == ["수리품"]
    assert got.year_from == 2020 and got.year_to == 2024
    assert got.price_min_won == 20_000_000
    assert got.price_max_won == 200_000_000
    assert got.hours_max == 8000
    assert got.skip_no_hours is True
    assert got.require_photo is True
    assert got.keyword == "DX"


def test_filter_partial_update(isolated_db):
    db = isolated_db
    db.upsert_user(1, "u")
    db.set_filter(UserFilter(chat_id=1, manufacturers=["볼보"], hours_max=5000))
    # Изменяем только manufacturers — hours_max должен сохраниться
    f = db.get_filter(1)
    f.manufacturers = []
    db.set_filter(f)
    got = db.get_filter(1)
    assert got.manufacturers == []
    assert got.hours_max == 5000


def test_seen_pids(isolated_db):
    db = isolated_db
    assert db.mark_seen(111, "100100") is True
    assert db.mark_seen(111, "100100") is False  # дубль
    assert db.is_seen(111)
    assert not db.is_seen(222)


def test_sent_table(isolated_db):
    db = isolated_db
    db.upsert_user(1, "u")
    assert db.mark_sent(1, 100) is True
    assert db.mark_sent(1, 100) is False
    assert db.was_sent(1, 100)
    assert not db.was_sent(1, 200)
    # clear_sent
    db.mark_sent(1, 200)
    assert db.clear_sent(1) == 2
    assert not db.was_sent(1, 100)


def test_cleanup_old_sent(isolated_db):
    from bot import config
    db = isolated_db
    db.upsert_user(1, "u")
    old = (datetime.now(timezone.utc) - timedelta(days=120)).isoformat(timespec="seconds")
    new = (datetime.now(timezone.utc) - timedelta(days=10)).isoformat(timespec="seconds")
    with sqlite3.connect(config.DB_PATH) as c:
        c.execute("INSERT INTO sent VALUES (?, ?, ?)", (1, 100, old))
        c.execute("INSERT INTO sent VALUES (?, ?, ?)", (1, 200, new))
    removed = db.cleanup_old_sent(days=90)
    assert removed == 1
    assert not db.was_sent(1, 100)
    assert db.was_sent(1, 200)


def test_favorites_crud(isolated_db):
    db = isolated_db
    db.upsert_user(1, "u")
    assert db.add_favorite(1, 100)
    assert not db.add_favorite(1, 100)   # дубль
    assert db.is_favorite(1, 100)
    assert db.count_favorites(1) == 1
    db.add_favorite(1, 200)
    db.add_favorite(1, 300)
    favs = db.list_favorites(1)
    assert set(favs) == {100, 200, 300}
    # ORDER BY added_at DESC, pid DESC — детерминированно
    assert favs[0] == 300
    assert db.remove_favorite(1, 200)
    assert not db.remove_favorite(1, 200)
    assert db.count_favorites(1) == 2


def test_favorites_with_model_and_pagination(isolated_db):
    db = isolated_db
    db.upsert_user(1, "u")
    db.add_favorite(1, 100, model="EC480")
    db.add_favorite(1, 200, model="DX380LC5")
    db.add_favorite(1, 300, model=None)            # без модели

    page = db.list_favorites_with_model(1, limit=2, offset=0)
    assert len(page) == 2
    # Свежие первыми
    assert page[0][0] == 300 and page[0][1] is None
    assert page[1][0] == 200 and page[1][1] == "DX380LC5"

    page2 = db.list_favorites_with_model(1, limit=2, offset=2)
    assert len(page2) == 1
    assert page2[0] == (100, "EC480")


def test_auto_admin_first_user(isolated_db):
    db = isolated_db
    # БД пустая → первый юзер становится админом
    db.upsert_user(111, "first")
    assert db.is_admin(111)
    # Второй — нет
    db.upsert_user(222, "second")
    assert not db.is_admin(222)
    assert db.list_admins() == [111]
    # Можно явно сделать админом
    db.set_admin(222, True)
    assert db.is_admin(222)
    assert set(db.list_admins()) == {111, 222}
    db.set_admin(111, False)
    assert not db.is_admin(111)


def test_blacklist_sellers_roundtrip(isolated_db):
    db = isolated_db
    db.upsert_user(1, "u")
    f = UserFilter(chat_id=1, blacklist_sellers=["대전어태치먼트", "기타"])
    db.set_filter(f)
    got = db.get_filter(1)
    assert got.blacklist_sellers == ["대전어태치먼트", "기타"]


def test_price_history(isolated_db):
    db = isolated_db
    import time
    db.record_price(123, 50_000_000)
    time.sleep(1.1)               # чтобы recorded_at различался (секунды)
    db.record_price(123, 45_000_000)
    time.sleep(1.1)
    db.record_price(123, 40_000_000)
    assert db.last_price(123) == 40_000_000
    assert db.previous_price(123) == 45_000_000
    hist = db.price_history(123)
    assert len(hist) == 3
    # ORDER BY recorded_at DESC — свежие первыми
    assert hist[0][1] == 40_000_000


def test_recipients_for_price_drop(isolated_db):
    db = isolated_db
    db.upsert_user(1, "a")
    db.upsert_user(2, "b")
    db.upsert_user(3, "c")
    # 1 — получал sent
    db.mark_sent(1, 999)
    # 2 — добавил в избранное
    db.add_favorite(2, 999)
    # 3 — ничего
    recipients = db.recipients_for_price_drop(999)
    assert recipients == {1, 2}
