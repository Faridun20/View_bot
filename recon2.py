"""
Второй проход разведки: качаем целевые страницы каталога.
Использует уже сохранённый storage_state.json (cookie CUPID уже там),
поэтому защиту проходить заново не нужно.
"""

from pathlib import Path
from playwright.sync_api import sync_playwright

OUT = Path("recon_out")
STATE = OUT / "storage_state.json"

TARGETS = {
    "20_category_100_excavators.html":      "https://www.4396200.com/sub8_1.html?cate_code=100",
    "21_subcat_100100_excavators_13.html":  "https://www.4396200.com/sub8_1_s.html?cate_code=100100",
    "22_subcat_100104_mini_excavators.html":"https://www.4396200.com/sub8_1_s.html?cate_code=100104",
    "23_category_101_dumps.html":           "https://www.4396200.com/sub8_1.html?cate_code=101",
    "24_subcat_101100_dump_19t.html":       "https://www.4396200.com/sub8_1_s.html?cate_code=101100",
    "25_item_9146671.html":                 "https://www.4396200.com/sub8_1_vvv.html?pid=9146671",
    "26_item_9094615.html":                 "https://www.4396200.com/sub8_1_vvv.html?pid=9094615",
    "27_search_sub9_1.html":                "https://www.4396200.com/sub9_1.html",
    "28_vip_v.html":                        "https://www.4396200.com/vip_v.html",
    "29_auction_exhibit.html":              "https://www.4396200.com/auction_exhibit.html",
}


def main() -> None:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            storage_state=str(STATE) if STATE.exists() else None,
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            locale="ko-KR",
        )
        page = context.new_page()

        for fname, url in TARGETS.items():
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=30000)
                page.wait_for_timeout(800)
                html = page.content()
                (OUT / fname).write_text(html, encoding="utf-8")
                print(f"[ok] {url} -> {fname} ({len(html)} б)")
            except Exception as e:
                print(f"[err] {url}: {e}")

        # Обновляем cookie на случай, если что-то поменялось
        context.storage_state(path=str(STATE))
        browser.close()


if __name__ == "__main__":
    main()
