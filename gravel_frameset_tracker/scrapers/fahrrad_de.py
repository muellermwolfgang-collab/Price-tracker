"""
fahrrad.de adapter -- DISABLED, likely not a fit for this bot.

Checked via search rather than a stub guess: fahrrad.de has frame-SIZE
calculators and complete-bike category pages (e.g.
/fahrraeder/rennrad/gravel-bikes/...) and wheel/component categories, but
no "buy a frame" category turned up anywhere for road or gravel -- unlike
bike-components.de and bike24.com, which both have a dedicated gravel
frame category. This matches the pattern seen with canyon.com: a retailer
that's built around complete bikes + accessories, not frame-only sales.

Left as a no-op rather than guessing a category URL that probably doesn't
exist. If you know fahrrad.de does sell standalone framesets somewhere I
didn't find, this is the place to implement it -- same interface as the
other adapters.
"""

from .base import Offer


def fetch_offers(page, model: dict) -> list[Offer]:
    return []
