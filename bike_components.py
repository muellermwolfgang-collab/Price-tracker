"""
bike-components.de adapter.

Category confirmed to exist: /en/components/frames/cyclocross-gravel/
Selectors below are a reasonable starting point (typical product-grid markup
for this class of shop) but are NOT verified against live HTML — check with
browser dev tools before relying on this. Update the SELECTORS dict below;
the rest of the function shouldn't need to change.
"""

import re
from .base import Offer

RETAILER = "bike-components.de"
CATEGORY_URL = "https://www.bike-components.de/en/components/frames/cyclocross-gravel/"

# TODO: verify these against the live page (dev tools -> inspect a product tile)
SELECTORS = {
    "product_tile": ".product-list-item, article.product",
    "title": ".product-list-item__title, .product-name",
    "price": ".product-list-item__price, .price",
    "link": "a",
}

PRICE_RE = re.compile(r"([\d.,]+)\s*€|€\s*([\d.,]+)")


def _parse_price(text: str) -> float | None:
    match = PRICE_RE.search(text)
    if not match:
        return None
    raw = match.group(1) or match.group(2)
    raw = raw.replace(".", "").replace(",", ".")
    try:
        return float(raw)
    except ValueError:
        return None


def _guess_material(title: str) -> str | None:
    lower = title.lower()
    if "carbon" in lower:
        return "carbon"
    if "alu" in lower:
        return "aluminium"
    return None


def fetch_offers(page, model: dict) -> list[Offer]:
    """Search the gravel-frame category for listings matching this model."""
    offers = []
    query = f"{model['brand']} {model['model']}"
    page.goto(CATEGORY_URL, wait_until="networkidle")

    # Site has an on-page search/filter — adjust selector for the actual
    # search input once verified.
    search_box = page.locator("input[type='search']").first
    if search_box.count():
        search_box.fill(query)
        search_box.press("Enter")
        page.wait_for_load_state("networkidle")

    tiles = page.locator(SELECTORS["product_tile"])
    for i in range(tiles.count()):
        tile = tiles.nth(i)
        title = tile.locator(SELECTORS["title"]).inner_text().strip()
        if model["brand"].lower() not in title.lower():
            continue

        price = _parse_price(tile.locator(SELECTORS["price"]).inner_text())
        material = _guess_material(title)
        if price is None or material is None or material not in model["materials"]:
            continue

        href = tile.locator(SELECTORS["link"]).first.get_attribute("href")
        offers.append(Offer(
            brand=model["brand"],
            model=model["model"],
            material=material,
            price_eur=price,
            size=None,  # size usually only visible on the product detail page
            url=href if href and href.startswith("http") else f"https://www.bike-components.de{href}",
            retailer=RETAILER,
        ))
    return offers
