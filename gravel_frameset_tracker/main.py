"""
Orchestrates the full run: discover new models -> scrape prices -> notify.

Run this on the same schedule as the tariff bot (cron / GitHub Actions /
whatever runner you're already using).
"""

from playwright.sync_api import sync_playwright

import discover_models
import scrape_prices
import notify


def main() -> None:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        print("Step 1/3: checking for new models...")
        try:
            discover_models.run(page)
        except Exception as exc:
            print(f"[main] discovery step failed, continuing anyway: {exc}")

        print("Step 2/3: scraping retailers for tracked models...")
        hits = []
        try:
            hits = scrape_prices.scrape_all(page)
        except Exception as exc:
            print(f"[main] scraping step failed: {exc}")

        print(f"Step 3/3: {len(hits)} offer(s) below threshold — notifying.")
        try:
            notify.notify_offers(hits)
        except Exception as exc:
            print(f"[main] notification step failed: {exc}")

        browser.close()


if __name__ == "__main__":
    main()
