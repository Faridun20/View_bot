"""Тесты сервисного слоя bot.catalog (обход каталога без сети).

Сетевой `get_session` подменяется фейком, который отдаёт HTML-фикстуры —
так проверяем, что единый слой (заменивший дублирующиеся обходы в
monitor и search) парсит список и карточки и правильно дедуплицирует pid.
"""
from __future__ import annotations

import pytest

from bot import catalog


class _FakeResp:
    def __init__(self, text: str) -> None:
        self.text = text


class _FakeSession:
    """Отдаёт listing-фикстуру на /sub8_1_s.html и item-фикстуру на /vvv."""

    def __init__(self, listing_html: str, item_html: str) -> None:
        self._listing = listing_html
        self._item = item_html
        self.calls: list[str] = []

    def get(self, url: str) -> _FakeResp:
        self.calls.append(url)
        if "sub8_1_s.html" in url:
            return _FakeResp(self._listing)
        return _FakeResp(self._item)


@pytest.fixture
def fake_catalog(recon_dir, monkeypatch):
    listing = (recon_dir / "21_subcat_100100_excavators_13.html").read_text(
        encoding="utf-8", errors="ignore")
    item = (recon_dir / "25_item_9146671.html").read_text(
        encoding="utf-8", errors="ignore")
    sess = _FakeSession(listing, item)
    monkeypatch.setattr(catalog, "get_session", lambda: sess)
    # Ограничиваем обход одной подкатегорией — фикстура одна.
    monkeypatch.setattr(catalog, "target_subcategories", lambda *, include_parts: ["100100"])
    return sess


def test_scan_previews_returns_sorted_desc(fake_catalog):
    previews = catalog.scan_previews()
    assert previews, "ожидали хотя бы один превью из фикстуры"
    pids = [p.pid for p in previews]
    # Сортировка по убыванию pid (свежие первыми)
    assert pids == sorted(pids, reverse=True)
    # Все уникальны (дедуп по pid)
    assert len(pids) == len(set(pids))


def test_scan_categories_matches_previews(fake_catalog):
    previews = catalog.scan_previews()
    cats = catalog.scan_categories()
    assert set(cats.keys()) == {p.pid for p in previews}
    # cate_code из обхода — это та подкатегория, что мы передали
    assert all(code == "100100" for code in cats.values())


def test_fetch_item_parses_card(fake_catalog):
    previews = catalog.scan_previews()
    pid = previews[0].pid
    item = catalog.fetch_item(pid)
    assert item is not None
    assert item.pid == pid
    # Хотя бы одно из ключевых полей должно распарситься (canary)
    assert item.model or item.manufacturer or item.price_raw


def test_fetch_latest_uses_top_preview(fake_catalog):
    item = catalog.fetch_latest()
    assert item is not None
    top_pid = catalog.scan_previews()[0].pid
    assert item.pid == top_pid


def test_scan_previews_survives_one_failing_category(recon_dir, monkeypatch):
    listing = (recon_dir / "21_subcat_100100_excavators_13.html").read_text(
        encoding="utf-8", errors="ignore")

    class _FlakySession:
        def get(self, url: str):
            if "100101" in url:
                raise RuntimeError("network boom")
            return _FakeResp(listing)

    monkeypatch.setattr(catalog, "get_session", lambda: _FlakySession())
    monkeypatch.setattr(catalog, "target_subcategories",
                        lambda *, include_parts: ["100101", "100100"])
    # Падение одной подкатегории не должно ронять весь обход.
    previews = catalog.scan_previews()
    assert previews
