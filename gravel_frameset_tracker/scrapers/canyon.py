"""
canyon.com adapter -- DISABLED pending manual check.

Fetched https://www.canyon.com/en-de/gravel/all-road/grail/grail-al/ and it
redirected to the general Grail category page ("Choose your Grail"), which
only lists complete bikes (Grail CF SL 7 AERO, Grail CFR Di2, Grail CF 8
1by, etc. -- all with groupsets/wheels specified, prices EUR 1,799-6,999).
No frame-only ("frameset") listing was visible on that page.

Two things this also confirmed, already reflected in models.json:
- The current Grail generation is carbon-only. There is no "Grail AL"
  anymore -- that variant has been discontinued.
- Whether Canyon sells the Grail as a standalone frameset at all right now
  is genuinely unclear from what I could fetch. It's possible there's a
  frame-only path via their "Customise" / "My Canyon Custom Bike" tool, or
  it may simply not be offered as a separate SKU currently.

Rather than guess selectors against a page structure I'm not confident
represents a real purchase path, this adapter is a no-op until confirmed.
If you check the site (or the Customise tool) and find a real frame-only
URL, this is the place to implement it -- same interface as the other
adapters.
"""

from .base import Offer


def fetch_offers(page, model: dict) -> list[Offer]:
    return []
