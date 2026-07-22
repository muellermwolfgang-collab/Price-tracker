"""
bike-components.de adapter.

Real category confirmed via fetch: /en/components/frames/cyclocross-gravel/
(52 items across 3 pages as of 2026-07-22). No on-page text search box was
found in the fetched page -- this iterates the paginated category listing
and matches product titles against the tracked model list, instead of
searching.

Price format on this site's /en/ pages is English-style: "1,000.00€"
(comma thousands separator, period decimal) -- confirmed from real listings
(e.g. "bc original Flint Gravel Frame ... 210.99€", "OPEN NEW U.P. Frameset
... 1,000.00€"). This is DIFFERENT from bike24.com's German-style format --
don't reuse this regex for other sites.

Selectors use link-href pattern matching (product URLs look like
/en/{Brand}/{Model-slug}-p{id}/?v={variant}) plus the link's visible text,
rather than guessed CSS classes -- classes weren't visible in what I could
fetch (page content, not raw DOM), but the URL/text patterns were, and are
more likely to survive a markup change anyway.
"""

import re
from .base import Offer

RETAILER = "bike-components.de"
CATEGORY_URL = "https://www.bike-components.de/en/components/frames/cyclocross-gravel/"
MAX_PAGES = 5  # confirmed 3 pages as of writing; capped higher in case inventory grows

PRICE_RE = re.compile(r"([\d,]+\.\d{2})\s*€")
PRODUCT_LINK_RE = re.compile(r"/en/[^/]+/[^/]+-p\d+/")


def _parse_price(text: str) -> float | None:
    match = PRICE_RE.search(text)
    if not match:
        return None
    return float(match.group(1).replace(",", ""))


def _guess_material(title: str) -> str | None:
    lower = title.lower()
    if "carbon" in lower:
        return "carbon"
    if "alu" in lower:
        return "aluminium"
    return None


def fetch_offers(page, model: dict) -> list[Offer]:
    offers = []
    search_term = model["model"].lower()
    brand_term = model["brand"].lower()

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

            text = link.inner_text().strip()
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
                size=None,  # size is chosen on the product detail page, not the listing
                url=href if href.startswith("http") else f"https://www.bike-components.de{href}",
                retailer=RETAILER,
            ))

        if not found_any_product_link:
            break  # ran past the last real page

    return offers
