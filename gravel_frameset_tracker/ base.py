"""
Shared interface for retailer scraper adapters.

Every adapter in this package implements a single function:

    fetch_offers(page, model: dict) -> list[Offer]

`page` is a Playwright page (already navigated to nothing in particular —
each adapter is responsible for its own navigation). `model` is one entry
from models.json, e.g.:

    {"brand": "Canyon", "model": "Grail CF", "materials": ["carbon"],
     "max_tire_clearance_mm": 42}

This keeps every adapter swappable and testable in isolation, and makes it
trivial to add a new retailer: copy an existing adapter, change the
navigation + CSS selectors, done.
"""

from dataclasses import dataclass


@dataclass
class Offer:
    brand: str
    model: str
    material: str          # "aluminium" or "carbon"
    price_eur: float
    size: str | None        # e.g. "56", or None if not stated on the listing
    url: str
    retailer: str
