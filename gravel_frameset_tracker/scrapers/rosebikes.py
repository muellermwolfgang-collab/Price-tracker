"""
rosebikes.de / rosebikes.com adapter -- DISABLED pending confirmation, but
with real findings worth acting on manually.

Rose is a strong candidate retailer -- German brand, and unlike canyon.com
and fahrrad.de they DO sell at least one frameset standalone: confirmed
real product page for the "Rose Xlite 06 Frameset"
(rosebikes.com/p/rose-xlite-06-frameset-2716879) -- but that's their
aero ROAD bike, not gravel, so out of scope here.

Their race-gravel platform, the Backroad FF, is confirmed via official
spec to have exactly 45mm tyre clearance -- right at your upper limit, and
a real candidate for the model list (added to models.json). However, I
could only find it sold as complete bikes (Backroad FF Red XPLR AXS,
GRX Di2, Classified 2x12, etc.) plus a frame/fork *crash-replacement*
parts document -- not a clear "buy the frameset new" retail page the way
Xlite 06 has. It's plausible one exists (Rose does sell some framesets
individually) but I couldn't confirm a URL for it.

Left disabled rather than guessing. Product URLs on this site follow the
pattern rosebikes.com/p/{model-slug}-{id} -- if you find a real Backroad
FF frameset page, this is the place to implement it, same interface as
the other adapters.
"""

from .base import Offer


def fetch_offers(page, model: dict) -> list[Offer]:
    return []
