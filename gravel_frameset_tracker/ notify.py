"""
Step 3: push notification.

Uses the same ntfy.sh topic as the tariff bot, so both push through one
channel to your phone -- no separate wiring needed.
"""

import requests
from scrapers.base import Offer


NTFY_TOPIC = "handysuche-iphone-xx2ab"  # same topic as the tariff bot


def send_notification(title: str, body: str) -> None:
    requests.post(
        f"https://ntfy.sh/{NTFY_TOPIC}",
        data=body.encode("utf-8"),
        headers={"Title": title},
        timeout=10,
    )


def notify_offers(offers: list[Offer]) -> None:
    if not offers:
        return
    lines = [
        f"{o.brand} {o.model} ({o.material}) — €{o.price_eur:.0f} @ {o.retailer}\n{o.url}"
        for o in offers
    ]
    send_notification(
        title=f"{len(offers)} Gravel-Rahmenset-Angebot(e) unter Schwelle",
        body="\n\n".join(lines),
    )
