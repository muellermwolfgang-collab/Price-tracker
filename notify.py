"""
Step 3: push notification.

WIRE THIS UP: replace the body of send_notification() with whatever the
iPhone-tariff bot already uses to push to your phone, so both bots notify
through the same channel. The placeholder below (ntfy.sh) works standalone
if you want to test this module before wiring it in — no account needed,
just install the ntfy app and subscribe to a topic name of your choosing.
"""

import requests
from scrapers.base import Offer


NTFY_TOPIC = "CHANGE-ME-to-a-private-topic-name"  # placeholder only


def send_notification(title: str, body: str) -> None:
    # --- placeholder implementation (ntfy.sh) ---
    requests.post(
        f"https://ntfy.sh/{NTFY_TOPIC}",
        data=body.encode("utf-8"),
        headers={"Title": title},
        timeout=10,
    )
    # --- replace above with your existing sender, e.g.: ---
    # from tariff_tracker.notify import send_notification as existing_sender
    # existing_sender(title, body)


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
