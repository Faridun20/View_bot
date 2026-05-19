"""Общие фикстуры pytest.

Главное: каждому тесту — свой DATA_DIR с изолированной БД, чтобы
никакая запись из одного теста не утекла в другой.
"""
from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path

import pytest


@pytest.fixture
def isolated_db(tmp_path, monkeypatch):
    """Изолированная БД для одного теста."""
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    # bot.config держит DATA_DIR в module-level — перезагружаем
    if "bot.config" in sys.modules:
        importlib.reload(sys.modules["bot.config"])
    # storage.db._db — синглтон, переинициализируется через init_db, но
    # ссылается на DEFAULT-путь. Поэтому также перезагрузим.
    if "bot.storage.db" in sys.modules:
        importlib.reload(sys.modules["bot.storage.db"])
    if "bot.storage" in sys.modules:
        importlib.reload(sys.modules["bot.storage"])

    from bot import config
    from bot.storage import init_db
    db = init_db(config.DB_PATH)
    yield db


@pytest.fixture
def recon_dir() -> Path:
    """Папка с HTML-фикстурами сайта для тестов парсера.

    Сюда коммитятся минимальные снапшоты — чтобы тесты были самодостаточны
    и проходили на CI (без обращения к настоящему сайту).
    """
    return Path(__file__).parent / "fixtures"
