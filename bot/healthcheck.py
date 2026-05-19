"""Минимальный HTTP-сервер для Railway healthcheck.

Поднимается, если задан env PORT (Railway автоматически даёт) или
HEALTHCHECK_PORT. Не блокирует основной polling-бот.

GET /        → 200 OK "ok"
GET /health  → 200 OK JSON со счётчиками подписчиков/лотов
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Optional

from aiohttp import web

from bot.storage.db import DB

logger = logging.getLogger(__name__)


def make_app(db: DB) -> web.Application:
    app = web.Application()

    async def root(_request: web.Request) -> web.Response:
        return web.Response(text="ok")

    async def health(_request: web.Request) -> web.Response:
        payload = {
            "status": "ok",
            "now_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "users_active": len(db.active_users()),
            "seen_pids": db.seen_count(),
        }
        return web.Response(
            text=json.dumps(payload, ensure_ascii=False),
            content_type="application/json",
        )

    app.add_routes([
        web.get("/", root),
        web.get("/health", health),
    ])
    return app


async def start_healthcheck(db: DB, port: int) -> Optional[web.AppRunner]:
    """Стартует aiohttp в фоне на 0.0.0.0:port. Возвращает runner для
    последующего shutdown (или None, если порт не задан)."""
    if not port:
        return None
    runner = web.AppRunner(make_app(db))
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    logger.info("Healthcheck-сервер запущен на 0.0.0.0:%d", port)
    return runner
