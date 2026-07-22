"""
Step 2: for every tracked model, ask every adapter for current offers,
and return the ones that beat the material-specific threshold.
"""

import json
from pathlib import Path

import config
from scrapers import ADAPTERS
from scrapers.base import Offer


def load_models() -> list[dict]:
    data = json.loads(Path(config.MODELS_FILE).read_text())
    return data["models"]


def below_threshold(offer: Offer) -> bool:
    if config.FRAME_SIZE_FILTER and offer.size and offer.size != config.FRAME_SIZE_FILTER:
        return False
    if offer.material == "aluminium":
        return offer.price_eur < config.THRESHOLD_ALUMINIUM_EUR
    if offer.material == "carbon":
        return offer.price_eur < config.THRESHOLD_CARBON_EUR
    return False


def scrape_all(page) -> list[Offer]:
    models = load_models()
    hits = []
    for model in models:
        for adapter in ADAPTERS:
            try:
                offers = adapter.fetch_offers(page, model)
            except Exception as exc:  # noqa: BLE001 - one bad adapter shouldn't kill the run
                print(f"[{adapter.RETAILER}] failed for {model['brand']} {model['model']}: {exc}")
                continue
            hits.extend(o for o in offers if below_threshold(o))
    return hits
