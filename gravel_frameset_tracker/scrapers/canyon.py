"""
canyon.com adapter — Canyon sells the Grail CF and Grail AL as standalone
framesets (confirmed via canyon.com/en-de/gravel/all-road/grail/). Only
covers Canyon models; fetch_offers() returns [] for anything else so it's
safe to include in the full adapter list unconditionally.

Selectors are a starting point, not verified against live HTML.
"""

import re
from .base import Offer

RETAILER = "canyon.com"
GRAIL_URLS = {
    "Grail CF": "https://www.canyon.com/en-de/gravel/all-road/grail/grail-cf/",
    "Grail AL": "https://www.canyon.com/en-de/gravel/all-road/grail/grail-al/",
}

# TODO: verify against live page
SELECTORS = {
    "variant_option": ".pdp-variant-selector__option",
    "price": ".pdp-price, .price__value",
    "size_selector": ".pdp-size-selector__option",
}

PRICE_RE = re.compile(r"([\d.,]+)")


def _parse_price(text: str) -> float | None:
    match = PRICE_RE.search(text.replace("€", ""))
    if not match:
        return None
    raw = match.group(1).replace(".", "").replace(",", ".")
    try:
        return float(raw)
    except ValueError:
        return None


def fetch_offers(page, model: dict) -> list[Offer]:
    url = GRAIL_URLS.get(model["model"])
    if not url:
        return []  # not a Canyon model this adapter knows about

    material = "carbon" if "carbon" in model["materials"] and model["model"] == "Grail CF" else (
        "aluminium" if model["model"] == "Grail AL" else None
    )
    if material is None:
        return []

    page.goto(url, wait_until="networkidle")

    # Frameset-only variant (as opposed to complete-bike builds) needs to be
    # selected explicitly — Canyon's PDP typically exposes this as one of
    # several "build" options.
    frameset_option = page.locator("text=/frameset/i").first
    if frameset_option.count():
        frameset_option.click()
        page.wait_for_timeout(500)

    price_el = page.locator(SELECTORS["price"]).first
    if not price_el.count():
        return []
    price = _parse_price(price_el.inner_text())
    if price is None:
        return []

    return [Offer(
        brand="Canyon",
        model=model["model"],
        material=material,
        price_eur=price,
        size=None,
        url=url,
        retailer=RETAILER,
    )]
