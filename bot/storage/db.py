"""Слой хранения: SQLite + минимальный набор операций.

Сознательно используется sqlite3 (sync) — БД маленькая, операции мгновенные.
В асинхронном коде вызываем через asyncio.to_thread.
"""
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _dumps(value) -> str | None:
    """JSON-сериализация для list/str с обрезкой пустых значений."""
    if value is None:
        return None
    if isinstance(value, (list, tuple, set)):
        items = [v for v in value if v]
        return json.dumps(items, ensure_ascii=False) if items else None
    return json.dumps(value, ensure_ascii=False)


def _loads_list(s: str | None) -> list[str]:
    if not s:
        return []
    try:
        data = json.loads(s)
        return [str(x) for x in data] if isinstance(data, list) else []
    except (json.JSONDecodeError, TypeError):
        return []


SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
  chat_id      INTEGER PRIMARY KEY,
  username     TEXT,
  active       INTEGER NOT NULL DEFAULT 1,
  created_at   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS filters (
  chat_id            INTEGER PRIMARY KEY REFERENCES users(chat_id) ON DELETE CASCADE,
  manufacturer       TEXT,        -- LEGACY: один производитель (для совместимости со старой версией)
  manufacturers      TEXT,        -- JSON-массив корейских названий, NULL = любой
  subcategories      TEXT,        -- JSON-массив cate_code (например ["100100","100104"])
  regions            TEXT,        -- JSON-массив коротких ключей регионов ("강원","경기")
  min_grade          INTEGER,     -- ранг 1..4 (B..A+), NULL = любой
  blacklist_keywords TEXT,        -- JSON-массив фраз-исключений
  year_from          INTEGER,
  year_to            INTEGER,
  price_min_won      INTEGER,
  price_max_won      INTEGER,
  hours_max          INTEGER,
  skip_no_hours      INTEGER NOT NULL DEFAULT 0,   -- 1 = не присылать лоты без часов
  require_photo      INTEGER NOT NULL DEFAULT 0,   -- 1 = только лоты с фото
  keyword            TEXT,        -- substring в model + description + manufacturer
  updated_at         TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS seen_pids (
  pid             INTEGER PRIMARY KEY,
  cate_code       TEXT,
  first_seen_at   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sent (
  chat_id   INTEGER NOT NULL,
  pid       INTEGER NOT NULL,
  sent_at   TEXT NOT NULL,
  PRIMARY KEY (chat_id, pid)
);

CREATE TABLE IF NOT EXISTS favorites (
  chat_id    INTEGER NOT NULL,
  pid        INTEGER NOT NULL,
  added_at   TEXT NOT NULL,
  note       TEXT,
  PRIMARY KEY (chat_id, pid)
);

CREATE INDEX IF NOT EXISTS idx_seen_first_seen ON seen_pids(first_seen_at);
CREATE INDEX IF NOT EXISTS idx_fav_chat ON favorites(chat_id, added_at DESC);
"""


@dataclass
class UserFilter:
    chat_id: int
    # Производители: пустой список = любой
    manufacturers: list[str] = field(default_factory=list)
    # Подкатегории (cate_code): пустой = все «машинные»
    subcategories: list[str] = field(default_factory=list)
    # Регионы (короткие ключи): пустой = любой
    regions: list[str] = field(default_factory=list)
    # Минимальный грейд (1..4): None = любой
    min_grade: int | None = None
    # Чёрный список — пустой = выключен
    blacklist_keywords: list[str] = field(default_factory=list)

    year_from: int | None = None
    year_to: int | None = None
    price_min_won: int | None = None
    price_max_won: int | None = None
    hours_max: int | None = None
    skip_no_hours: bool = False
    require_photo: bool = False
    keyword: str | None = None

    def is_empty(self) -> bool:
        return not any([
            self.manufacturers, self.subcategories, self.regions,
            self.min_grade, self.blacklist_keywords,
            self.year_from, self.year_to,
            self.price_min_won, self.price_max_won,
            self.hours_max, self.skip_no_hours, self.require_photo,
            self.keyword,
        ])


class DB:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._init()

    def _conn(self) -> sqlite3.Connection:
        c = sqlite3.connect(self.path)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA foreign_keys = ON")
        return c

    def _init(self) -> None:
        with self._conn() as c:
            # WAL: writer не блокирует readers (и наоборот), а конкурентные
            # writers сериализуются на ~миллисекунды. Без него monitor.run_scan
            # и /search упирались бы друг в друга при одновременной записи.
            c.execute("PRAGMA journal_mode=WAL")
            c.execute("PRAGMA synchronous=NORMAL")   # быстрее, при WAL безопасно
            c.executescript(SCHEMA)
            self._migrate(c)

    def _migrate(self, c: sqlite3.Connection) -> None:
        """Дотягиваем существующую БД до текущей схемы (ALTER TABLE по нужде).

        SQLite не умеет 'IF NOT EXISTS' для колонок, поэтому смотрим вручную.
        """
        cols = {r["name"] for r in c.execute("PRAGMA table_info(filters)")}
        adders = [
            ("manufacturers",      "TEXT"),
            ("subcategories",      "TEXT"),
            ("regions",            "TEXT"),
            ("min_grade",          "INTEGER"),
            ("blacklist_keywords", "TEXT"),
            ("price_min_won",      "INTEGER"),
            ("skip_no_hours",      "INTEGER NOT NULL DEFAULT 0"),
            ("require_photo",      "INTEGER NOT NULL DEFAULT 0"),
        ]
        for name, decl in adders:
            if name not in cols:
                c.execute(f"ALTER TABLE filters ADD COLUMN {name} {decl}")

        # Перенос старого скалярного manufacturer в JSON manufacturers
        if "manufacturer" in cols:
            for r in c.execute(
                "SELECT chat_id, manufacturer, manufacturers FROM filters "
                "WHERE manufacturer IS NOT NULL AND manufacturer != '' "
                "AND (manufacturers IS NULL OR manufacturers = '')"
            ):
                c.execute(
                    "UPDATE filters SET manufacturers = ? WHERE chat_id = ?",
                    (json.dumps([r["manufacturer"]], ensure_ascii=False),
                     r["chat_id"]),
                )

    # ---- users -----------------------------------------------------------

    def upsert_user(self, chat_id: int, username: str | None) -> None:
        with self._conn() as c:
            c.execute(
                """
                INSERT INTO users(chat_id, username, active, created_at)
                VALUES(?, ?, 1, ?)
                ON CONFLICT(chat_id) DO UPDATE SET
                  username = excluded.username,
                  active = 1
                """,
                (chat_id, username, _now_iso()),
            )

    def deactivate_user(self, chat_id: int) -> None:
        with self._conn() as c:
            c.execute("UPDATE users SET active = 0 WHERE chat_id = ?", (chat_id,))

    def active_users(self) -> list[int]:
        with self._conn() as c:
            return [r["chat_id"] for r in c.execute("SELECT chat_id FROM users WHERE active = 1")]

    def is_active(self, chat_id: int) -> bool:
        with self._conn() as c:
            r = c.execute("SELECT active FROM users WHERE chat_id = ?", (chat_id,)).fetchone()
        return bool(r and r["active"])

    def set_active(self, chat_id: int, active: bool) -> None:
        """Включить/выключить почасовые автоуведомления, не удаляя пользователя."""
        with self._conn() as c:
            c.execute("UPDATE users SET active = ? WHERE chat_id = ?",
                      (1 if active else 0, chat_id))

    # ---- filters ---------------------------------------------------------

    def get_filter(self, chat_id: int) -> UserFilter:
        with self._conn() as c:
            r = c.execute("SELECT * FROM filters WHERE chat_id = ?", (chat_id,)).fetchone()
        if r is None:
            return UserFilter(chat_id=chat_id)
        keys = r.keys()

        def col(name, default=None):
            return r[name] if name in keys else default

        # manufacturers — может быть в JSON-колонке; если её ещё нет (старая
        # запись), берём legacy-колонку manufacturer.
        manufacturers = _loads_list(col("manufacturers"))
        if not manufacturers and col("manufacturer"):
            manufacturers = [col("manufacturer")]

        return UserFilter(
            chat_id=r["chat_id"],
            manufacturers=manufacturers,
            subcategories=_loads_list(col("subcategories")),
            regions=_loads_list(col("regions")),
            min_grade=col("min_grade"),
            blacklist_keywords=_loads_list(col("blacklist_keywords")),
            year_from=r["year_from"],
            year_to=r["year_to"],
            price_min_won=col("price_min_won"),
            price_max_won=r["price_max_won"],
            hours_max=r["hours_max"],
            skip_no_hours=bool(col("skip_no_hours", 0)),
            require_photo=bool(col("require_photo", 0)),
            keyword=r["keyword"],
        )

    def set_filter(self, f: UserFilter) -> None:
        with self._conn() as c:
            c.execute(
                """
                INSERT INTO filters(
                    chat_id, manufacturer, manufacturers, subcategories,
                    regions, min_grade, blacklist_keywords,
                    year_from, year_to, price_min_won, price_max_won,
                    hours_max, skip_no_hours, require_photo, keyword, updated_at
                ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(chat_id) DO UPDATE SET
                  manufacturer       = excluded.manufacturer,
                  manufacturers      = excluded.manufacturers,
                  subcategories      = excluded.subcategories,
                  regions            = excluded.regions,
                  min_grade          = excluded.min_grade,
                  blacklist_keywords = excluded.blacklist_keywords,
                  year_from          = excluded.year_from,
                  year_to            = excluded.year_to,
                  price_min_won      = excluded.price_min_won,
                  price_max_won      = excluded.price_max_won,
                  hours_max          = excluded.hours_max,
                  skip_no_hours      = excluded.skip_no_hours,
                  require_photo      = excluded.require_photo,
                  keyword            = excluded.keyword,
                  updated_at         = excluded.updated_at
                """,
                (
                    f.chat_id,
                    # legacy: первый из списка — чтобы старая колонка осталась корректной
                    f.manufacturers[0] if f.manufacturers else None,
                    _dumps(f.manufacturers),
                    _dumps(f.subcategories),
                    _dumps(f.regions),
                    f.min_grade,
                    _dumps(f.blacklist_keywords),
                    f.year_from, f.year_to,
                    f.price_min_won, f.price_max_won,
                    f.hours_max, int(bool(f.skip_no_hours)),
                    int(bool(f.require_photo)),
                    f.keyword,
                    _now_iso(),
                ),
            )

    def reset_filter(self, chat_id: int) -> None:
        with self._conn() as c:
            c.execute("DELETE FROM filters WHERE chat_id = ?", (chat_id,))

    # ---- seen_pids -------------------------------------------------------

    def mark_seen(self, pid: int, cate_code: str | None = None) -> bool:
        """Помечает pid виденным. Возвращает True, если pid новый."""
        with self._conn() as c:
            cur = c.execute(
                """
                INSERT INTO seen_pids(pid, cate_code, first_seen_at)
                VALUES(?, ?, ?)
                ON CONFLICT(pid) DO NOTHING
                """,
                (pid, cate_code, _now_iso()),
            )
            return cur.rowcount > 0

    def mark_seen_bulk(self, pids: Iterable[tuple[int, str | None]]) -> int:
        """Помечает много pid сразу (для seed). Возвращает число добавленных."""
        added = 0
        with self._conn() as c:
            for pid, cate in pids:
                cur = c.execute(
                    """INSERT INTO seen_pids(pid, cate_code, first_seen_at)
                       VALUES(?, ?, ?) ON CONFLICT(pid) DO NOTHING""",
                    (pid, cate, _now_iso()),
                )
                added += cur.rowcount
        return added

    def is_seen(self, pid: int) -> bool:
        with self._conn() as c:
            return c.execute("SELECT 1 FROM seen_pids WHERE pid = ?", (pid,)).fetchone() is not None

    def seen_count(self) -> int:
        with self._conn() as c:
            return c.execute("SELECT COUNT(*) FROM seen_pids").fetchone()[0]

    # ---- sent ------------------------------------------------------------

    def mark_sent(self, chat_id: int, pid: int) -> bool:
        with self._conn() as c:
            cur = c.execute(
                """INSERT INTO sent(chat_id, pid, sent_at)
                   VALUES(?, ?, ?) ON CONFLICT DO NOTHING""",
                (chat_id, pid, _now_iso()),
            )
            return cur.rowcount > 0

    def was_sent(self, chat_id: int, pid: int) -> bool:
        with self._conn() as c:
            return c.execute(
                "SELECT 1 FROM sent WHERE chat_id = ? AND pid = ?", (chat_id, pid)
            ).fetchone() is not None

    def clear_sent(self, chat_id: int) -> int:
        """Удалить историю отправленных лотов для одного пользователя.
        Возвращает число удалённых записей."""
        with self._conn() as c:
            cur = c.execute("DELETE FROM sent WHERE chat_id = ?", (chat_id,))
            return cur.rowcount

    def cleanup_old_sent(self, days: int = 90) -> int:
        """Удалить записи sent старше N дней. seen_pids НЕ трогаем —
        иначе старые лоты могут вернуться в поток уведомлений."""
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat(timespec="seconds")
        with self._conn() as c:
            cur = c.execute("DELETE FROM sent WHERE sent_at < ?", (cutoff,))
            return cur.rowcount

    # ---- favorites -----------------------------------------------------

    def add_favorite(self, chat_id: int, pid: int, note: str | None = None) -> bool:
        """True если добавили (раньше не было), False если уже было."""
        with self._conn() as c:
            cur = c.execute(
                """INSERT INTO favorites(chat_id, pid, added_at, note)
                   VALUES(?, ?, ?, ?) ON CONFLICT DO NOTHING""",
                (chat_id, pid, _now_iso(), note),
            )
            return cur.rowcount > 0

    def remove_favorite(self, chat_id: int, pid: int) -> bool:
        with self._conn() as c:
            cur = c.execute("DELETE FROM favorites WHERE chat_id = ? AND pid = ?",
                            (chat_id, pid))
            return cur.rowcount > 0

    def is_favorite(self, chat_id: int, pid: int) -> bool:
        with self._conn() as c:
            r = c.execute("SELECT 1 FROM favorites WHERE chat_id = ? AND pid = ?",
                          (chat_id, pid)).fetchone()
        return r is not None

    def list_favorites(self, chat_id: int, limit: int = 50) -> list[int]:
        # tie-break по pid DESC: при равном added_at (timespec=seconds) лоты,
        # добавленные в одну секунду, всё равно идут в детерминированном
        # порядке (новые pid обычно появились позже).
        with self._conn() as c:
            rows = c.execute(
                "SELECT pid FROM favorites WHERE chat_id = ? "
                "ORDER BY added_at DESC, pid DESC LIMIT ?",
                (chat_id, limit),
            ).fetchall()
        return [r["pid"] for r in rows]

    def count_favorites(self, chat_id: int) -> int:
        with self._conn() as c:
            return c.execute("SELECT COUNT(*) FROM favorites WHERE chat_id = ?",
                             (chat_id,)).fetchone()[0]


_db: DB | None = None


def init_db(path: Path) -> DB:
    global _db
    if _db is None:
        _db = DB(path)
    return _db
