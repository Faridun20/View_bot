"""Слой хранения: SQLite + минимальный набор операций.

Сознательно используется sqlite3 (sync) — БД маленькая, операции мгновенные.
В асинхронном коде вызываем через asyncio.to_thread.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
  chat_id      INTEGER PRIMARY KEY,
  username     TEXT,
  active       INTEGER NOT NULL DEFAULT 1,
  created_at   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS filters (
  chat_id        INTEGER PRIMARY KEY REFERENCES users(chat_id) ON DELETE CASCADE,
  manufacturer   TEXT,       -- например '볼보' (точное название с сайта)
  year_from      INTEGER,
  year_to        INTEGER,
  price_max_won  INTEGER,
  hours_max      INTEGER,
  keyword        TEXT,       -- substring-поиск в model + description (case-insensitive)
  updated_at     TEXT NOT NULL
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

CREATE INDEX IF NOT EXISTS idx_seen_first_seen ON seen_pids(first_seen_at);
"""


@dataclass
class UserFilter:
    chat_id: int
    manufacturer: str | None = None
    year_from: int | None = None
    year_to: int | None = None
    price_max_won: int | None = None
    hours_max: int | None = None
    keyword: str | None = None

    def is_empty(self) -> bool:
        return not any([
            self.manufacturer, self.year_from, self.year_to,
            self.price_max_won, self.hours_max, self.keyword,
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
            c.executescript(SCHEMA)

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

    # ---- filters ---------------------------------------------------------

    def get_filter(self, chat_id: int) -> UserFilter:
        with self._conn() as c:
            r = c.execute("SELECT * FROM filters WHERE chat_id = ?", (chat_id,)).fetchone()
        if r is None:
            return UserFilter(chat_id=chat_id)
        return UserFilter(
            chat_id=r["chat_id"],
            manufacturer=r["manufacturer"],
            year_from=r["year_from"],
            year_to=r["year_to"],
            price_max_won=r["price_max_won"],
            hours_max=r["hours_max"],
            keyword=r["keyword"],
        )

    def set_filter(self, f: UserFilter) -> None:
        with self._conn() as c:
            c.execute(
                """
                INSERT INTO filters(chat_id, manufacturer, year_from, year_to,
                                    price_max_won, hours_max, keyword, updated_at)
                VALUES(?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(chat_id) DO UPDATE SET
                  manufacturer = excluded.manufacturer,
                  year_from    = excluded.year_from,
                  year_to      = excluded.year_to,
                  price_max_won= excluded.price_max_won,
                  hours_max    = excluded.hours_max,
                  keyword      = excluded.keyword,
                  updated_at   = excluded.updated_at
                """,
                (f.chat_id, f.manufacturer, f.year_from, f.year_to,
                 f.price_max_won, f.hours_max, f.keyword, _now_iso()),
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


_db: DB | None = None


def init_db(path: Path) -> DB:
    global _db
    if _db is None:
        _db = DB(path)
    return _db
