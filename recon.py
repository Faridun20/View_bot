"""
Разведка сайта 4396200.com.

Открывает сайт через Playwright (автоматически проходит Cupid-защиту, JS сам
расшифровывает cookie), затем:
1. Сохраняет HTML главной страницы.
2. Извлекает все внутренние ссылки и записывает их в links.txt.
3. Скачивает первые N внутренних страниц для последующего анализа.
4. Сохраняет storage_state.json — состояние сессии с cookie CUPID,
   чтобы потом ходить без браузера через requests.
"""

import json
import re
from pathlib import Path
from urllib.parse import urljoin, urlparse

from playwright.sync_api import sync_playwright

BASE = "https://www.4396200.com"
OUT = Path("recon_out")
OUT.mkdir(exist_ok=True)

MAX_SUBPAGES = 15  # скачать первые N внутренних страниц


def is_internal(url: str) -> bool:
    try:
        host = urlparse(url).netloc
    except Exception:
        return False
    return host == "" or host.endswith("4396200.com")


def safe_name(url: str) -> str:
    name = re.sub(r"[^a-zA-Z0-9._-]+", "_", url)
    return name[:120] or "index"


def main() -> None:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            locale="ko-KR",
        )
        page = context.new_page()

        print(f"[1/4] Открываю {BASE} (пройду Cupid)…")
        page.goto(BASE, wait_until="networkidle", timeout=60000)
        # Cupid редиректит через ?ckattempt=1, ждём финальный URL
        page.wait_for_load_state("networkidle", timeout=30000)
        final_url = page.url
        print(f"      финальный URL: {final_url}")

        html = page.content()
        (OUT / "00_home.html").write_text(html, encoding="utf-8")
        print(f"      сохранил 00_home.html ({len(html)} байт)")

        # Сохраняем storage_state (cookies, etc.) — пригодится для requests
        context.storage_state(path=str(OUT / "storage_state.json"))
        print("      сохранил storage_state.json")

        # Извлекаем все ссылки
        print("[2/4] Извлекаю ссылки…")
        hrefs = page.eval_on_selector_all(
            "a[href]", "els => els.map(e => e.href)"
        )
        # тексты ссылок — полезно для понимания меню
        link_pairs = page.eval_on_selector_all(
            "a[href]",
            "els => els.map(e => ({href: e.href, text: (e.innerText||'').trim().slice(0,80)}))",
        )

        internal = sorted({u for u in hrefs if is_internal(u)})
        (OUT / "links.txt").write_text("\n".join(internal), encoding="utf-8")
        (OUT / "links_with_text.json").write_text(
            json.dumps(link_pairs, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"      найдено внутренних ссылок: {len(internal)}")

        # Скачиваем первые N внутренних страниц
        print(f"[3/4] Скачиваю первые {MAX_SUBPAGES} внутренних страниц…")
        seen = {final_url.rstrip("/")}
        downloaded = 0
        for url in internal:
            if downloaded >= MAX_SUBPAGES:
                break
            url = url.split("#")[0]
            if url.rstrip("/") in seen:
                continue
            seen.add(url.rstrip("/"))
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=30000)
                page.wait_for_timeout(500)
                html = page.content()
                fname = f"{downloaded + 1:02d}_{safe_name(url)}.html"
                (OUT / fname).write_text(html, encoding="utf-8")
                print(f"      [{downloaded + 1}] {url} -> {fname} ({len(html)} б)")
                downloaded += 1
            except Exception as e:
                print(f"      [skip] {url}: {e}")

        print("[4/4] Готово. См. папку recon_out/")
        browser.close()


if __name__ == "__main__":
    main()
