"""
bike24.com adapter.

Real category confirmed via fetch:
/cycling/parts/bike-frames/cyclocross-gravel-bike-frames (paginated via
?page=N, confirmed real inventory as of 2026-07-22 includes e.g. "Ridley
Kanzo Fast - Carbon Frame Set - 2025", "BMC KAIUS 01 - Carbon Gravel Frame
Set - 2026").

Price format on this site is German-style: "988,24 €" (period thousands
separator, comma decimal, space before €) -- confirmed from real listings.
This is DIFFERENT from bike-components.de's English-style format -- each
adapter parses its own site's format, don't share the regex.

Uses link-href pattern matching (product pages are bike24.com/p{id}.html)
plus the link's visible text, same reasoning as bike_components.py: I
could confirm real URL/text patterns via fetch but not real CSS classes.

PERFORMANCE NOTE: same fetch-once-per-run caching as bike_components.py --
see that file's docstring for why this matters.
"""

import re
from pathlib import Path
from .base import Offer

RETAILER = "bike24.de"
CATEGORY_URL = "https://www.bike24.com/cycling/parts/bike-frames/cyclocross-gravel-bike-frames"
MAX_PAGES = 5  # confirmed at least 2 pages as of writing; capped higher in case inventory grows

PRICE_RE = re.compile(r"([\d.]+,\d{2})\s*€")
PRODUCT_LINK_RE = re.compile(r"/p\d+\.html")

MATERIAL_KEYWORDS = ["carbon", "aluminium", "alu", "titanium", "steel"]

_product_cache: list[tuple[str, str]] | None = None  # [(link text, href), ...]


def _parse_price(text: str) -> float | None:
    match = PRICE_RE.search(text)
    if not match:
        return None
    raw = match.group(1).replace(".", "").replace(",", ".")
    return float(raw)


def _guess_material(title: str) -> str | None:
    lower = title.lower()
    if "carbon" in lower:
        return "carbon"
    if "alu" in lower:
        return "aluminium"
    # titanium/steel intentionally not mapped -- not in our two threshold buckets
    return None


def _get_all_products(page) -> list[tuple[str, str]]:
    """Fetch and paginate the category once; cache for the rest of the run."""
    global _product_cache
    if _product_cache is not None:
        return _product_cache

    products = []
    for page_num in range(1, MAX_PAGES + 1):
        url = CATEGORY_URL if page_num == 1 else f"{CATEGORY_URL}?page={page_num}"
        page.goto(url, wait_until="domcontentloaded", timeout=30000)
        page.wait_for_timeout(2000)  # let JS-rendered product tiles settle

        links = page.locator("a").all()
        found_any_product_link = False
        for link in links:
            href = link.get_attribute("href") or ""
            if not PRODUCT_LINK_RE.search(href):
                continue
            found_any_product_link = True
            products.append((link.inner_text().strip(), href))

        if not found_any_product_link:
            if page_num == 1:
                # Unexpected -- the category is confirmed to have real listings
                # (e.g. Ridley Kanzo Fast). Zero matches on page 1 means Playwright
                # is seeing something different than a plain fetch does (cookie
                # banner, lazy-loaded grid, bot detection, etc.) -- capture what
                # it actually sees instead of guessing which.
                try:
                    page.screenshot(path="debug_bike24_page1.png", full_page=True)
                    Path("debug_bike24_page1.html").write_text(page.content())
                    print("[bike24.de] no product links found on page 1 -- "
                          "saved debug_bike24_page1.png / .html for inspection")
                except Exception as exc:
                    print(f"[bike24.de] no product links found on page 1, "
                          f"and debug capture also failed: {exc}")
            break

    _product_cache = products
    return products


def fetch_offers(page, model: dict) -> list[Offer]:
    offers = []
    search_term = model["model"].lower()
    brand_term = model["brand"].lower()

    for text, href in _get_all_products(page):
        lower_text = text.lower()
        if brand_term not in lower_text and search_term not in lower_text:
            continue

        price = _parse_price(text)
        material = _guess_material(text)
        if price is None or material is None or material not in model["materials"]:
            continue

        offers.append(Offer(
            brand=model["brand"],
            model=model["model"],
            material=material,
            price_eur=price,
            size=None,
            url=href if href.startswith("http") else f"https://www.bike24.com{href}",
            retailer=RETAILER,
        ))

    return offers
