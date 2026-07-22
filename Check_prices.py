"""
Price tracker for iPhone 17 / 17 Pro / 17 Pro Max mobile contract bundles.

Checks handyhase.de and logitel.de for offers matching:
- provider Vodafone or Telekom
- at least `min_data_gb` of data
- no "Young" or "GigaKombi"/"Kombi" tariffs
- effective price below the per-device threshold

Sends a push notification via ntfy.sh when a qualifying offer is found.

NOTE FOR FIRST RUN: this is a first version written without being able to
test against the live sites from this environment. If a source returns
0 offers, the script prints a chunk of the raw page text it saw - paste
that back to Claude so the regex can be adjusted together.
"""

import json
import re
import sys
from pathlib import Path

import requests
from bs4 import BeautifulSoup

CONFIG_PATH = Path(__file__).parent / "config.json"
STATE_PATH = Path(__file__).parent / "state.json"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    )
}


def load_json(path, default):
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return default


def save_json(path, data):
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def to_float(euro_str):
    """Turn '52,95' or '1.059,00' into a float."""
    cleaned = euro_str.strip().replace(".", "").replace(",", ".")
    return float(cleaned)


def first_price(text):
    """Return the first '12,34' style amount found in a text chunk, or None."""
    m = re.search(r"(\d{1,4},\d{2})\s*€", text)
    return to_float(m.group(1)) if m else None


def fetch_text(url):
    resp = requests.get(url, headers=HEADERS, timeout=20)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "lxml")
    return soup.get_text("\n", strip=True)


# ---------------------------------------------------------------------------
# Handyhase parser
# ---------------------------------------------------------------------------
def parse_handyhase(text):
    """
    Returns a list of offers:
    {provider, tariff, data_gb, months, monthly_fee, device_cost,
     bonus, effective_price}
    Handyhase already publishes its own "Effektivpreis" per offer, so we
    read that number directly instead of computing it ourselves.
    """
    offers = []

    # Build a tariff-name -> network lookup from the detail section
    # ("Tarif: X ... Netz: Y").
    network_by_tariff = {}
    for m in re.finditer(
        r"Tarif:\s*(?P<name>.+?)\n.*?Netz:\s*(?P<netz>\w+)",
        text,
        re.DOTALL,
    ):
        network_by_tariff[m.group("name").strip()] = m.group("netz").strip()

    # Step 1: find the start of every offer block (tariff name immediately
    # followed by "X Monate" and "Netz" and a data volume). Each match gives
    # us where a block starts; the next match's start (or end of text) is
    # where it ends.
    anchor_pattern = re.compile(
        r"(?P<tariff>[^\n]+?)\n"
        r"(?P<months>\d+)\s*Monate\n"
        r"Netz\n"
        r"(?P<data>endlos|\d+)\s*GB?\s*5G"
    )
    anchors = list(anchor_pattern.finditer(text))

    for i, anchor in enumerate(anchors):
        block_start = anchor.end()
        block_end = anchors[i + 1].start() if i + 1 < len(anchors) else len(text)
        block = text[block_start:block_end]

        fee_m = re.search(r"monatlich\n?\s*([\d,]+)\s*€", block)
        device_m = re.search(r"Gerät einmalig\n?\s*([\d,]+)\s*€", block)
        eff_m = re.search(r"Handyhase Effektivpreis\n?\s*monatlich\s*([\d,]+)\s*€", block)
        bonus_m = re.search(r"([\d,]+)\s*€\s*Bonus", block)

        if not (fee_m and device_m and eff_m):
            continue  # this block didn't match the expected shape - skip it

        tariff = anchor.group("tariff").strip()
        data_gb = 999 if anchor.group("data") == "endlos" else int(anchor.group("data"))

        offers.append(
            {
                "provider": network_by_tariff.get(tariff, "unbekannt"),
                "tariff": tariff,
                "data_gb": data_gb,
                "months": int(anchor.group("months")),
                "monthly_fee": to_float(fee_m.group(1)),
                "device_cost": to_float(device_m.group(1)),
                "bonus": to_float(bonus_m.group(1)) if bonus_m else 0.0,
                "effective_price": to_float(eff_m.group(1)),
            }
        )
    return offers


# ---------------------------------------------------------------------------
# Logitel parser
# ---------------------------------------------------------------------------
KNOWN_PROVIDERS = (
    "Vodafone", "Telekom", "freenet", "o2", "congstar",
    "klarmobil", "Blau", "otelo", "allmobil",
)


def parse_logitel(text, market_value_eur, months):
    """
    Logitel doesn't publish a netted effective price, so we compute one
    ourselves using the same style of formula Handyhase uses:
    (monthly_fee * months + device_cost + connection fee + shipping - bonus
     - market_value) / months

    Note: Logitel's price widgets render the Euro-cents part separately from
    the Euro part (a common responsive-design trick), which can cause a
    plain text extraction to see the same amount fragmented or duplicated.
    That's why we always take the FIRST plausible "xx,xx €" match after each
    label rather than assuming a clean single number.
    """
    offers = []

    # A card starts with a known provider name at the start of a line,
    # e.g. "Vodafone Smart L" or "Telekom MagentaMobil L mit Handy".
    anchor_pattern = re.compile(
        r"^(?P<provider>" + "|".join(KNOWN_PROVIDERS) + r")\s+(?P<tariff>[^\n]+)$",
        re.MULTILINE,
    )
    anchors = list(anchor_pattern.finditer(text))

    for i, anchor in enumerate(anchors):
        block_start = anchor.end()
        block_end = anchors[i + 1].start() if i + 1 < len(anchors) else len(text)
        block = text[block_start:block_end]

        data_m = re.search(r"(\d+)\s*GB\s*5G", block)
        device_m = re.search(r"Gerät einm\.?\s*nur:\s*([\d,]+)\s*€", block)
        bonus_m = re.search(r"(\d+)\s*€\s*Wechselbonus", block)
        connection_m = re.search(r"Anschlusspreis:?\s*\n?\s*(Gratis|[\d,]+)\s*€?", block)
        shipping_m = re.search(r"Versandkosten\s*([\d,]+)\s*€", block)

        if not (data_m and device_m):
            continue  # doesn't look like a full tariff card - skip

        # Monthly fee: first price-looking number that appears strictly
        # between the device cost and the "Anschlusspreis" label.
        device_end = device_m.end()
        connection_start = connection_m.start() if connection_m else len(block)
        fee = first_price(block[device_end:connection_start])
        if fee is None:
            continue

        connection_raw = connection_m.group(1) if connection_m else "0"
        connection = 0.0 if connection_raw == "Gratis" else to_float(connection_raw)
        shipping = to_float(shipping_m.group(1)) if shipping_m else 0.0
        bonus = float(bonus_m.group(1)) if bonus_m else 0.0
        device_cost = to_float(device_m.group(1))

        total = fee * months + device_cost + connection + shipping - bonus - market_value_eur
        effective_price = round(total / months, 2)

        offers.append(
            {
                "provider": anchor.group("provider"),
                "tariff": anchor.group("tariff").strip(),
                "data_gb": int(data_m.group(1)),
                "months": months,
                "monthly_fee": fee,
                "device_cost": device_cost,
                "bonus": bonus,
                "effective_price": effective_price,
            }
        )
    return offers


def passes_filters(offer, config):
    if offer["provider"] not in config["provider_filter"]:
        return False
    if offer["data_gb"] < config["min_data_gb"]:
        return False
    name = offer["tariff"]
    for bad_word in config["exclude_name_contains"]:
        if bad_word.lower() in name.lower():
            return False
    return True


def send_ntfy(topic, title, message):
    if not topic or topic.startswith("REPLACE"):
        print("WARNING: no ntfy topic configured - skipping notification.")
        return
    requests.post(
        f"https://ntfy.sh/{topic}",
        data=message.encode("utf-8"),
        headers={"Title": title.encode("utf-8"), "Priority": "high"},
        timeout=10,
    )


def main():
    config = load_json(CONFIG_PATH, {})
    state = load_json(STATE_PATH, {})

    for device in config["devices"]:
        device_name = device["name"]
        threshold = device["threshold_effective_price"]
        market_value = device["market_value_eur"]

        for source in device["sources"]:
            site = source["site"]
            url = source["url"]
            print(f"\n--- {device_name} / {site} ---")

            try:
                text = fetch_text(url)
            except Exception as exc:
                print(f"Could not fetch {url}: {exc}")
                continue

            if site == "handyhase":
                offers = parse_handyhase(text)
            elif site == "logitel":
                offers = parse_logitel(text, market_value, config["contract_months"])
            else:
                print(f"Unknown site '{site}', skipping.")
                continue

            print(f"Found {len(offers)} raw offers.")
            if not offers:
                # Nothing matched - print a slice of the page text so the
                # regex can be fixed together.
                print("No offers parsed. First 800 chars of page text:")
                print(text[:800])
                continue

            for offer in offers:
                if not passes_filters(offer, config):
                    continue

                key = (
                    f"{site}|{device_name}|{offer['provider']}|"
                    f"{offer['tariff']}|{offer['data_gb']}"
                )
                eff = offer["effective_price"]
                print(f"  {offer['provider']:10s} {offer['tariff'][:40]:40s} "
                      f"{offer['data_gb']:>3}GB  eff. {eff:.2f} €")

                if eff < threshold and state.get(key) != eff:
                    send_ntfy(
                        config["ntfy_topic"],
                        f"{device_name}: {eff:.2f} €/Monat!",
                        f"{offer['provider']} {offer['tariff']} "
                        f"({offer['data_gb']} GB) bei {site} - "
                        f"Effektivpreis {eff:.2f} €/Monat",
                    )
                    state[key] = eff
                    print(f"  -> ALERT sent ({eff:.2f} € < {threshold} €)")

    save_json(STATE_PATH, state)


if __name__ == "__main__":
    main()
