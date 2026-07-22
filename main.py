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
        discover_models.run(page)

        print("Step 2/3: scraping retailers for tracked models...")
        hits = scrape_prices.scrape_all(page)

        print(f"Step 3/3: {len(hits)} offer(s) below threshold — notifying.")
        notify.notify_offers(hits)

        browser.close()


if __name__ == "__main__":
    main()
