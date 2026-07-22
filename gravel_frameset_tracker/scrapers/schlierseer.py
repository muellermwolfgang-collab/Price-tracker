"""
schlierseer-bikeparts.de adapter -- DISABLED, structurally incompatible
with price-threshold scraping.

Real gravel/cross category confirmed via fetch: /cross -- and it's a
genuinely relevant retailer (Cube frame specialist / parts-out shop,
relevant since you ride a Cube Agree). It carries plenty of Cube Nuroad
framesets in both aluminium ("Alu Superlite") and carbon ("C:62"
SLX/Race/Pro/EX grades).

The problem: this is an inquiry-based shop, not a fixed-price catalogue.
Every listing on /cross is an individual physical frame (unique inventory
number, e.g. "NR-084"), and pricing is explicitly NOT published --
"Set-Preis von den jeweiligen Komponenten abhängig" (set price depends on
which components you choose) -- you contact them for a quote per frame.
There is no "€" figure anywhere on the category page to scrape.

This means a price-threshold bot fundamentally can't work against their
own site as-is -- there's no price to read. Their eBay shop
(schlierseerradhausonlineshop) DOES show real prices for some of the same
Nuroad framesets (confirmed one at EUR 499 for an alloy Nuroad, size S),
so that could be a path if you want this retailer covered -- but that's a
different, harder scraping target (eBay's anti-bot measures) and I
haven't verified it. Left disabled rather than pretending there's a price
to parse.

Not added to models.json either: Cube Nuroad's tire clearance against
your 32-45mm rule isn't confirmed, and it's somewhat tangential while
this specific site can't supply a price anyway.
"""

from .base import Offer


def fetch_offers(page, model: dict) -> list[Offer]:
    return []
