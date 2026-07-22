"""
Price tracker for iPhone 17 / 17 Pro / 17 Pro Max mobile contract bundles.

Checks handyhase.de, logitel.de and check24.de for offers matching:
- provider Vodafone or Telekom
- at least `min_data_gb` of data
- no "Young" or "GigaKombi"/"Kombi" tariffs
- effective price below the per-device threshold

Sends a push notification via ntfy.sh when a qualifying offer is found.
Check24 is fetched with a headless Chromium browser (Playwright) because
its tariff list is rendered by JavaScript after the page loads. The
browser is launched once per run and reused across devices, since
starting Chromium itself (not the page loads) was the slow part.
"""

import json
import re
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
    """Return the first euro amount found in a text chunk, or None.
    Handles Logitel's price rendering, where the cents are in a separate
    DOM node from the euros, so a line break can land between the comma
    and the two cent digits (e.g. "44,\n99 €" really means 44,99 €)."""
    m = re.search(r"(\d{1,4}),\s*(\d{2})\s*€", text)
    if not m:
        return None
    return float(f"{m.group(1)}.{m.group(2)}")


def fetch_text(url):
    resp = requests.get(url, headers=HEADERS, timeout=20)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "lxml")
    return soup.get_text("\n", strip=True)


def launch_browser():
    """Start one headless Chromium instance to be reused across every
    browser-based fetch in this run. Launching Chromium is the slow part
    (process start-up, not the page loads) - starting it once instead of
    once per device cuts real runtime noticeably. Returns (pw_cm, browser);
    call pw_cm.__exit__(None, None, None) when done to shut it down."""
    from playwright.sync_api import sync_playwright

    pw_cm = sync_playwright()
    pw = pw_cm.__enter__()
    browser = pw.chromium.launch()
    return pw_cm, browser


def fetch_text_browser(browser, url, wait_ms=8000, extra_click_labels=()):
    """Fetch a page using an already-running browser instance. Needed for
    sites like Check24 that build the tariff list with JavaScript after
    the page loads - a plain HTTP fetch only sees an empty shell there.
    Clicks away the cookie banner if one appears, optionally clicks other
    labels (e.g. an "apply filters" button some sites need before showing
    real tariffs), then waits for the list to render. Uses a fresh browser
    *context* per call (cheap - just an isolated cookie/session jar) so
    pages don't leak state between devices, while the expensive browser
    *process* itself is only started once per run."""
    context = browser.new_context(user_agent=HEADERS["User-Agent"], locale="de-DE")
    try:
        page = context.new_page()
        page.goto(url, timeout=60000, wait_until="domcontentloaded")
        for label in ("Nur notwendige Cookies", "alle akzeptieren", "Akzeptieren"):
            try:
                page.get_by_text(label, exact=False).first.click(timeout=3000)
                break
            except Exception:
                continue
        for label in extra_click_labels:
            try:
                page.get_by_text(label, exact=False).first.click(timeout=3000)
            except Exception:
                pass
        page.wait_for_timeout(wait_ms)  # give the JS app time to load tariffs
        return page.inner_text("body")
    finally:
        context.close()


# ---------------------------------------------------------------------------
# Check24 parser
# ---------------------------------------------------------------------------
def parse_check24(text, market_value_eur, months):
    """
    Check24 offer cards are anchored on "(über <shop>)" - the fulfillment
    shop name. Right after that comes: tariff name, delivery estimate,
    then data volume ("Unlimited" or "<N> GB") as the 3rd non-empty line.
    Further down, "Ø pro Monat" holds the pre-computed average monthly
    cost (device value NOT netted out, per Check24's own explanation
    text), so effective_price = avg - market_value/months, same idea as
    Handyhase/Logitel.

    Check24 shows the network only as a logo icon, never as text, so we
    infer it from well-known tariff-name branding (MagentaMobil ->
    Telekom, "Smart ..." -> Vodafone, "Mobile Unlimited"/"Blue" -> o2).
    Generic reseller tariffs like "Allnet Flat X GB" give no reliable
    signal and stay "unbekannt" - safer to miss an offer than to
    mislabel its network.
    """
    offers = []
    seen = set()

    anchor_pattern = re.compile(r"\(über\s+([^)]+)\)")
    anchors = list(anchor_pattern.finditer(text))

    for i, anchor in enumerate(anchors):
        shop = anchor.group(1).strip()
        block_start = anchor.end()
        block_end = anchors[i + 1].start() if i + 1 < len(anchors) else len(text)
        block = text[block_start:block_end]

        lines = [ln.strip() for ln in block.split("\n") if ln.strip()]
        if len(lines) < 3:
            continue
        tariff = lines[0]
        data_line = lines[2]

        if data_line == "Unlimited":
            data_gb = 9999
        else:
            dm = re.match(r"(\d+)\s*GB", data_line)
            if not dm:
                continue
            data_gb = int(dm.group(1))

        avg_m = re.search(r"Ø\s*pro\s*Monat\s*([\d,]+)\s*€", block)
        if not avg_m:
            continue
        avg = to_float(avg_m.group(1))

        low = tariff.lower()
        if "magenta" in low:
            provider = "Telekom"
        elif low.startswith("smart"):
            provider = "Vodafone"
        elif "mobile unlimited" in low or low.startswith("blue"):
            provider = "o2"
        else:
            provider = "unbekannt"

        effective_price = round(avg - market_value_eur / months, 2)

        dedup_key = (provider, tariff, data_gb, avg, shop)
        if dedup_key in seen:
            continue
        seen.add(dedup_key)

        offers.append(
            {
                "provider": provider,
                "tariff": f"{tariff} ({shop})",
                "data_gb": data_gb,
                "months": months,
                "monthly_fee": avg,
                "device_cost": 0.0,
                "bonus": 0.0,
                "effective_price": effective_price,
            }
        )
    return offers


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

    network_by_tariff = {}
    for m in re.finditer(
        r"Tarif:\s*(?P<name>.+?)\n.*?Netz:\s*(?P<netz>\w+)",
        text,
        re.DOTALL,
    ):
        network_by_tariff[m.group("name").strip()] = m.group("netz").strip()

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
            continue

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
    """
    offers = []

    anchor_pattern = re.compile(
        r"^(?P<provider>" + "|".join(KNOWN_PROVIDERS) + r")\s+(?P<tariff>[^\n]+)",
        re.MULTILINE,
    )
    anchors = list(anchor_pattern.finditer(text))

    seen = set()
    for i, anchor in enumerate(anchors):
        block_start = anchor.end()
        block_end = anchors[i + 1].start() if i + 1 < len(anchors) else len(text)
        block = text[block_start:block_end]

        data_m = re.search(r"(\d+)\s*GB\s*5G", block)
        device_m = re.search(r"Gerät einm\.?\s*nur:\s*([\d,]+)\s*€", block)
        bonus_m = re.search(r"(\d+)\s*€\s*(?:Wechselbonus|Cashback|Guthaben|Online-Bonus)", block)
        connection_m = re.search(r"Anschlusspreis:?\s*\n?\s*(Gratis|[\d,]+)\s*€?", block)
        shipping_m = re.search(r"Versandkosten\s*([\d,]+)\s*€", block)

        if not (data_m and device_m):
            continue

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
        tariff = anchor.group("tariff").strip()
        data_gb = int(data_m.group(1))

        total = fee * months + device_cost + connection + shipping - bonus - market_value_eur
        effective_price = round(total / months, 2)

        dedup_key = (anchor.group("provider"), tariff, data_gb, fee, device_cost)
        if dedup_key in seen:
            continue
        seen.add(dedup_key)

        offers.append(
            {
                "provider": anchor.group("provider"),
                "tariff": tariff,
                "data_gb": data_gb,
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
    if len(name) > 70:
        return False
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

    needs_browser = any(
        source["site"] == "check24"
        for device in config["devices"]
        for source in device["sources"]
    )
    pw_cm, browser = (launch_browser() if needs_browser else (None, None))

    try:
        for device in config["devices"]:
            device_name = device["name"]
            threshold = device["threshold_effective_price"]
            market_value = device["market_value_eur"]

            for source in device["sources"]:
                site = source["site"]
                url = source["url"]
                print(f"\n--- {device_name} / {site} ---")

                try:
                    if site == "check24":
                        text = fetch_text_browser(browser, url)
                    else:
                        text = fetch_text(url)
                except Exception as exc:
                    print(f"Could not fetch {url}: {exc}")
                    continue

                if site == "handyhase":
                    offers = parse_handyhase(text)
                elif site == "logitel":
                    offers = parse_logitel(text, market_value, config["contract_months"])
                elif site == "check24":
                    offers = parse_check24(text, market_value, config["contract_months"])
                else:
                    print(f"Unknown site '{site}', skipping.")
                    continue

                print(f"Found {len(offers)} raw offers.")
                if not offers:
                    landmarks = {
                        "handyhase": "Effektivpreis",
                        "logitel": "Tarifempfehlungen",
                        "check24": "über",
                    }
                    landmark = landmarks.get(site, "€")
                    idx = text.find(landmark)
                    if idx == -1:
                        print(
                            f"Landmark '{landmark}' not found ANYWHERE in the fetched "
                            f"page. This suggests the tariff content is loaded by "
                            f"JavaScript after the page loads, so a plain HTTP fetch "
                            f"never sees it - a regex fix alone won't solve this."
                        )
                        print("First 500 chars fetched:")
                        print(text[:500])
                    else:
                        print(f"Landmark '{landmark}' found at position {idx}. Text around it:")
                        print(text[idx:idx + 1500])
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
    finally:
        if pw_cm:
            pw_cm.__exit__(None, None, None)

    save_json(STATE_PATH, state)


if __name__ == "__main__":
    main()
