"""
bike24.de adapter — STUB. Search URL pattern below is a guess based on
typical bike24 structure; verify and replace SELECTORS before use.
"""

from .base import Offer

RETAILER = "bike24.de"
SEARCH_URL = "https://www.bike24.com/search?query={query}"

# TODO: fill in after inspecting the live search-results page
SELECTORS = {
    "product_tile": ".product-tile",
    "title": ".product-tile__title",
    "price": ".product-tile__price",
    "link": "a",
}


def fetch_offers(page, model: dict) -> list[Offer]:
    query = f"{model['brand']} {model['model']} rahmenset".replace(" ", "+")
    page.goto(SEARCH_URL.format(query=query), wait_until="networkidle")

    # TODO: implement once SELECTORS are verified — same shape as
    # scrapers/bike_components.py: iterate product tiles, filter by brand
    # match, parse price, guess material, append Offer.
    return []
