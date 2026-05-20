"""Тесты типизированного Settings."""
from __future__ import annotations

from pathlib import Path

from bot.config import Settings, _bool, _int


def test_defaults():
    s = Settings()
    assert s.monitor_interval_minutes == 60
    assert s.include_parts is False
    assert s.admin_ids == []


def test_from_env_reads_values(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("MONITOR_INTERVAL_MINUTES", "15")
    monkeypatch.setenv("INCLUDE_PARTS", "true")
    monkeypatch.setenv("ADMIN_IDS", "111, 222 ,abc")
    monkeypatch.setenv("PRICE_CHECK_TOP_N", "5")
    s = Settings.from_env()
    assert s.monitor_interval_minutes == 15
    assert s.include_parts is True
    assert s.admin_ids == [111, 222]          # 'abc' отброшено
    assert s.price_check_top_n == 5
    assert s.db_path == tmp_path / "bot.db"
    assert s.cupid_storage == tmp_path / "storage_state.json"


def test_int_helper_handles_garbage(monkeypatch):
    monkeypatch.setenv("X_INT", "")
    assert _int("X_INT", 42) == 42
    monkeypatch.setenv("X_INT", "notanumber")
    assert _int("X_INT", 7) == 7
    monkeypatch.setenv("X_INT", "13")
    assert _int("X_INT", 7) == 13


def test_bool_helper(monkeypatch):
    for truthy in ("1", "true", "YES", "On"):
        monkeypatch.setenv("X_BOOL", truthy)
        assert _bool("X_BOOL", False) is True
    for falsy in ("0", "false", "no", ""):
        monkeypatch.setenv("X_BOOL", falsy)
        assert _bool("X_BOOL", True) is False


def test_port_falls_back_to_healthcheck_port(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.delenv("PORT", raising=False)
    monkeypatch.setenv("HEALTHCHECK_PORT", "8080")
    assert Settings.from_env().healthcheck_port == 8080
