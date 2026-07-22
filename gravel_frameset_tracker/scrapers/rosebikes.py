"""
rosebikes.de adapter — STUB. Verify search URL and selectors before use.
"""

from .base import Offer

RETAILER = "rosebikes.de"
SEARCH_URL = "https://www.rosebikes.de/suche?q={query}"

# TODO: fill in after inspecting the live search-results page
SELECTORS = {
    "product_tile": ".product-tile",
    "title": ".product-tile__name",
    "price": ".product-tile__price",
    "link": "a",
}


def fetch_offers(page, model: dict) -> list[Offer]:
    query = f"{model['brand']} {model['model']} rahmenset".replace(" ", "+")
    page.goto(SEARCH_URL.format(query=query), wait_until="networkidle")

    # TODO: same pattern as scrapers/bike_components.py once verified
    return []
