"""
Price extraction for the black_week module.

Everything in here works on plain strings (rendered HTML, visible text,
text blocks) and never touches the network or Playwright, so it can be
unit-tested with saved HTML samples.

Extraction order (first hit wins for `price`):
  1. JSON-LD  (Product -> offers: Offer / AggregateOffer)
  2. Meta tags (product:price:amount, og:price:amount, itemprop="price")
  3. `price_selector` from targets.yaml
  4. listing pages only: visible offer tiles / text blocks containing `match`

For listing pages the offer tiles are always collected into `offers`
(with title, price and condition), even if the price came from step 1-3.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from bs4 import BeautifulSoup

# --------------------------------------------------------------------------
# German price parsing
# --------------------------------------------------------------------------

# One amount, optionally preceded or followed by a euro sign / "EUR".
# Accepts "1.299,00", "209,99", "1299", "99,-", "99,–", "1.299", "1299.00".
_AMOUNT = r"\d{1,3}(?:\.\d{3})+(?:,(?:\d{1,2}|-|–))?|\d+(?:,(?:\d{1,2}|-|–))?|\d+\.\d{2}(?!\d)"
_EURO_AFTER = re.compile(rf"(?<![\d.,])({_AMOUNT})\s*(?:€|EUR\b|Euro\b)", re.IGNORECASE)
_EURO_BEFORE = re.compile(rf"(?:€|EUR\b)\s*({_AMOUNT})(?![\d,])", re.IGNORECASE)


def parse_price(value) -> float | None:
    """Turn a price in German (or machine) notation into a float.

    "1.299,00 €" -> 1299.0, "209,99 €" -> 209.99, "ab 164,25 €" -> 164.25,
    "99,- €" -> 99.0, "1299.00" (JSON-LD) -> 1299.0, 49 -> 49.0.
    Returns None if no amount can be found.
    """
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value) if value >= 0 else None
    text = str(value).strip().replace("\xa0", " ").replace(" ", " ")
    if not text:
        return None
    m = re.search(r"\d[\d.,\s]*(?:,[-–])?", text)
    if not m:
        return None
    num = re.sub(r"\s+", "", m.group(0)).rstrip(".,")
    num = re.sub(r",[-–]$", "", num)
    if "," in num and "." in num:
        # whichever separator comes last is the decimal separator
        if num.rfind(",") > num.rfind("."):
            num = num.replace(".", "").replace(",", ".")      # 1.299,00
        else:
            num = num.replace(",", "")                        # 1,299.00
    elif "," in num:
        head, _, tail = num.rpartition(",")
        if len(tail) == 3 and head.replace(",", "").isdigit():
            num = num.replace(",", "")                        # 1,299 (thousands)
        else:
            num = head.replace(",", "") + "." + tail          # 209,99
    elif "." in num:
        head, _, tail = num.rpartition(".")
        if len(tail) == 3:
            num = num.replace(".", "")                        # 1.299 (thousands)
        elif num.count(".") > 1:
            num = num.replace(".", "", num.count(".") - 1)
    try:
        price = float(num)
    except ValueError:
        return None
    return round(price, 2)


_SHIPPING_CTX = re.compile(r"(versand|lieferung|liefer|porto|zzgl)", re.IGNORECASE)
_EXCLUDE_CTX = re.compile(
    r"(/\s*monat|mtl\.?|monatlich|pro monat|rate|finanzier|/\s*stk|grundpreis|/\s*kg|/\s*m²|/\s*m\b|pfand)",
    re.IGNORECASE,
)
_FREE_SHIPPING = re.compile(
    r"(versandkostenfrei|kostenlose[rn]?\s+(?:versand|lieferung)|gratis\s*(?:versand|lieferung)|"
    r"versand\s*(?::|\s)\s*(?:kostenlos|gratis|frei|0,00\s*€))(?!\s*ab)",
    re.IGNORECASE,
)


def find_euro_amounts(text: str) -> list[tuple[float, int, int]]:
    """All euro amounts in a text as (value, start, end)."""
    text = (text or "").replace("\xa0", " ").replace(" ", " ")
    found: dict[int, tuple[float, int, int]] = {}
    for rx in (_EURO_AFTER, _EURO_BEFORE):
        for m in rx.finditer(text):
            val = parse_price(m.group(1))
            if val is not None and m.start() not in found:
                found[m.start()] = (val, m.start(), m.end())
    return sorted(found.values(), key=lambda t: t[1])


def find_shipping(text: str) -> float | None:
    """Shipping cost from a short text, if recognisable. 0.0 = free shipping."""
    text = (text or "").replace("\xa0", " ")
    if _FREE_SHIPPING.search(text):
        return 0.0
    for val, start, end in find_euro_amounts(text):
        before = text[max(0, start - 30):start]
        after = text[end:end + 25]
        if re.search(r"(versand|versandkosten|lieferung|porto)\s*:?\s*$", before, re.IGNORECASE) or (
            re.search(r"zzgl\.?\s*$", before, re.IGNORECASE)
            and re.match(r"[ \t]*(versand|lieferung|porto)", after, re.IGNORECASE)
        ):
            return val
    return None


def shipping_near_price(text: str, price: float, before: int = 150, after: int = 350) -> float | None:
    """Shipping cost from the page text, but only right around the displayed
    price. Searching the whole page picks up banners, filters ("versandkostenfrei")
    or footers that have nothing to do with this product."""
    text = (text or "").replace("\xa0", " ").replace("\u202f", " ")
    for val, start, end in find_euro_amounts(text):
        if abs(val - price) < 0.005:
            return find_shipping(text[max(0, start - before):end + after])
    return None


def offer_prices(text: str) -> list[float]:
    """Euro amounts in a text block that look like an item price
    (skips shipping, monthly rates, unit prices)."""
    text = (text or "").replace("\xa0", " ")
    prices = []
    for val, start, end in find_euro_amounts(text):
        # only look at the same line: tiles put price and shipping on separate lines
        before = text[max(0, start - 25):start].rsplit("\n", 1)[-1]
        after = text[end:end + 15].split("\n", 1)[0]
        if _SHIPPING_CTX.search(before[-15:]) or re.match(r"[ \t]*(versand|lieferung|porto)", after, re.I):
            continue
        if _EXCLUDE_CTX.search(after) or _EXCLUDE_CTX.search(before[-12:]):
            continue
        if val <= 0:
            continue
        prices.append(val)
    return prices


# --------------------------------------------------------------------------
# Result type
# --------------------------------------------------------------------------

@dataclass
class Extraction:
    price: float | None = None
    currency: str | None = None
    shipping: float | None = None
    availability: str | None = None
    source: str | None = None           # jsonld / meta / selector / listing
    price_high: float | None = None     # AggregateOffer highPrice
    offer_count: int | None = None      # AggregateOffer offerCount
    name: str | None = None             # product name from JSON-LD, if any
    offers: list[dict] = field(default_factory=list)  # listing offers


# --------------------------------------------------------------------------
# 1. JSON-LD
# --------------------------------------------------------------------------

def _as_list(x):
    if x is None:
        return []
    return x if isinstance(x, list) else [x]


def _types(node: dict) -> set[str]:
    return {str(t).split("/")[-1] for t in _as_list(node.get("@type"))}


def _iter_nodes(data):
    """Walk any JSON-LD structure and yield every dict node."""
    stack = [data]
    while stack:                      # depth-first, in document order
        node = stack.pop()
        if isinstance(node, list):
            stack.extend(reversed(node))
        elif isinstance(node, dict):
            yield node
            stack.extend(reversed([v for v in node.values() if isinstance(v, (dict, list))]))


def _load_jsonld_blocks(soup: BeautifulSoup) -> list:
    blocks = []
    for tag in soup.find_all("script", attrs={"type": re.compile(r"application/ld\+json", re.I)}):
        raw = tag.string or tag.get_text() or ""
        raw = raw.strip()
        if not raw:
            continue
        # strip HTML comments / CDATA wrappers some shops put around JSON-LD
        raw = re.sub(r"^\s*(<!--|<!\[CDATA\[)", "", raw)
        raw = re.sub(r"(-->|\]\]>)\s*$", "", raw)
        try:
            blocks.append(json.loads(raw, strict=False))
        except ValueError:
            continue
    return blocks


def _short_availability(value) -> str | None:
    if not value:
        return None
    v = value[0] if isinstance(value, list) else value
    if isinstance(v, dict):
        v = v.get("@id") or v.get("name")
    return str(v).rstrip("/").split("/")[-1] or None


def _shipping_from_offer(offer: dict) -> float | None:
    for sd in _as_list(offer.get("shippingDetails")):
        if not isinstance(sd, dict):
            continue
        for rate in _as_list(sd.get("shippingRate")):
            if isinstance(rate, dict):
                val = parse_price(rate.get("value", rate.get("price")))
                if val is not None:
                    return val
    return None


def _offer_price(offer: dict) -> tuple[float | None, str | None]:
    price = parse_price(offer.get("price"))
    currency = offer.get("priceCurrency")
    if price is None:
        for spec in _as_list(offer.get("priceSpecification")):
            if isinstance(spec, dict):
                price = parse_price(spec.get("price"))
                currency = currency or spec.get("priceCurrency")
                if price is not None:
                    break
    return price, currency


def _extract_offers(offers_field) -> Extraction | None:
    """Turn a Product's `offers` into an Extraction (cheapest offer wins)."""
    best: Extraction | None = None
    for offer in _as_list(offers_field):
        if not isinstance(offer, dict):
            continue
        types = _types(offer)
        if "AggregateOffer" in types or "lowPrice" in offer:
            low = parse_price(offer.get("lowPrice"))
            high = parse_price(offer.get("highPrice"))
            count = offer.get("offerCount")
            inner = _extract_offers(offer.get("offers")) if offer.get("offers") else None
            if low is None and inner is not None:
                low = inner.price
            if low is None:
                low = parse_price(offer.get("price"))
            if low is None:
                continue
            try:
                count = int(count) if count is not None else None
            except (TypeError, ValueError):
                count = None
            cand = Extraction(
                price=low,
                currency=offer.get("priceCurrency") or (inner.currency if inner else None),
                shipping=_shipping_from_offer(offer) if _shipping_from_offer(offer) is not None
                else (inner.shipping if inner else None),
                availability=_short_availability(offer.get("availability"))
                or (inner.availability if inner else None),
                source="jsonld",
                price_high=high,
                offer_count=count,
            )
        else:
            price, currency = _offer_price(offer)
            if price is None:
                continue
            cand = Extraction(
                price=price,
                currency=currency,
                shipping=_shipping_from_offer(offer),
                availability=_short_availability(offer.get("availability")),
                source="jsonld",
            )
        if best is None or cand.price < best.price:
            best = cand
    return best


def _match_regex(match: str | None):
    if not match:
        return None
    tokens = [re.escape(t) for t in match.split()]
    # "SE 3" also matches "SE3" / "SE-3", but not "SE 30"
    return re.compile(r"(?<![\w])" + r"[\s\-]*".join(tokens) + r"(?![\d])", re.IGNORECASE)


def matches(text: str, match: str | None) -> bool:
    rx = _match_regex(match)
    return True if rx is None else bool(rx.search(text or ""))


def extract_jsonld(html_or_soup, match: str | None = None) -> Extraction | None:
    """Price from JSON-LD Product data.

    Without `match` (product pages) the first Product with a price wins, i.e.
    the page's main product, not a cheaper accessory from a carousel. With
    `match` (listing pages) the cheapest product whose name contains the
    keyword wins."""
    soup = html_or_soup if isinstance(html_or_soup, BeautifulSoup) else BeautifulSoup(html_or_soup, "lxml")
    best: Extraction | None = None
    for block in _load_jsonld_blocks(soup):
        for node in _iter_nodes(block):
            types = _types(node)
            if not types & {"Product", "ProductGroup", "IndividualProduct", "ProductModel"}:
                continue
            if match and not matches(str(node.get("name", "")), match):
                continue
            ext = _extract_offers(node.get("offers"))
            if ext is None:
                continue
            if isinstance(node.get("name"), str):
                ext.name = node["name"].strip()[:300] or None
            if not match:
                return ext
            if best is None or ext.price < best.price:
                best = ext
    return best


# --------------------------------------------------------------------------
# 2. Meta tags
# --------------------------------------------------------------------------

def _meta(soup: BeautifulSoup, *names: str) -> str | None:
    for name in names:
        tag = soup.find("meta", attrs={"property": name}) or soup.find("meta", attrs={"name": name})
        if tag and tag.get("content"):
            return tag["content"].strip()
    return None


def extract_meta(html_or_soup) -> Extraction | None:
    soup = html_or_soup if isinstance(html_or_soup, BeautifulSoup) else BeautifulSoup(html_or_soup, "lxml")
    raw = _meta(soup, "product:price:amount", "og:price:amount")
    currency = _meta(soup, "product:price:currency", "og:price:currency")
    availability = _meta(soup, "product:availability", "og:availability")
    if raw is None:
        tag = soup.find(attrs={"itemprop": "price"})
        if tag is not None:
            raw = tag.get("content") or tag.get_text(" ", strip=True)
            cur = soup.find(attrs={"itemprop": "priceCurrency"})
            if cur is not None:
                currency = currency or cur.get("content") or cur.get_text(strip=True)
            av = soup.find(attrs={"itemprop": "availability"})
            if av is not None:
                availability = availability or av.get("href") or av.get("content")
    price = parse_price(raw)
    if price is None:
        return None
    return Extraction(
        price=price,
        currency=currency or ("EUR" if raw and "€" in raw else None),
        availability=_short_availability(availability),
        source="meta",
    )


# --------------------------------------------------------------------------
# 3. CSS selector from config
# --------------------------------------------------------------------------

def extract_selector(html_or_soup, selector: str | None) -> Extraction | None:
    if not selector:
        return None
    soup = html_or_soup if isinstance(html_or_soup, BeautifulSoup) else BeautifulSoup(html_or_soup, "lxml")
    try:
        nodes = soup.select(selector)
    except Exception:
        return None
    for node in nodes:
        text = node.get("content") or node.get_text(" ", strip=True)
        amounts = find_euro_amounts(text)
        price = amounts[0][0] if amounts else parse_price(text)
        if price is not None:
            return Extraction(price=price, currency="EUR", source="selector")
    return None


# --------------------------------------------------------------------------
# 4. Listing tiles
# --------------------------------------------------------------------------

CONDITIONS = [
    "Premium", "Wie neu", "Neuwertig", "Hervorragend", "Exzellent", "Sehr gut",
    "Stark genutzt", "Akzeptabel", "Gut", "Neu",
]
_COND_RX = re.compile(
    r"(?:zustand\s*:?\s*)?(" + "|".join(re.escape(c) for c in CONDITIONS) + r")\b",
    re.IGNORECASE,
)


def find_condition(text: str) -> str | None:
    m = re.search(r"zustand\s*:?\s*([A-Za-zÄÖÜäöüß ]{2,20}?)(?:\s*[\n,|]|$)", text or "", re.IGNORECASE)
    if m and _COND_RX.match(m.group(1).strip()):
        return _canonical_condition(m.group(1).strip())
    m = _COND_RX.search(text or "")
    return _canonical_condition(m.group(1)) if m else None


def _canonical_condition(raw: str) -> str:
    for c in CONDITIONS:
        if raw.lower().startswith(c.lower()):
            return c
    return raw


def parse_listing_blocks(blocks: list[str], match: str | None, limit: int = 50) -> list[dict]:
    """Turn text blocks (one per visible offer tile) into offer dicts."""
    offers, seen = [], set()
    for block in blocks:
        if not block or not matches(block, match):
            continue
        prices = offer_prices(block)
        if not prices:
            continue
        lines = [ln.strip() for ln in re.split(r"[\r\n]+", block) if ln.strip()]
        title = next((ln for ln in lines if matches(ln, match)), lines[0] if lines else "")
        title = re.sub(r"\s+", " ", title)[:200]
        offer = {
            "title": title,
            "price": min(prices),
            "condition": find_condition(block),
            "shipping": find_shipping(block),
        }
        key = (offer["title"], offer["price"], offer["condition"])
        if key in seen:
            continue
        seen.add(key)
        offers.append(offer)
        if len(offers) >= limit:
            break
    return offers


_BLOCK_TAGS = ["article", "li", "a", "div", "section", "tr"]


def listing_blocks_from_html(html_or_soup, match: str | None) -> list[str]:
    """Static fallback for listing tiles (used in tests and when the
    in-browser collection fails): smallest elements whose text contains
    `match` and a euro amount."""
    soup = html_or_soup if isinstance(html_or_soup, BeautifulSoup) else BeautifulSoup(html_or_soup, "lxml")
    for t in soup(["script", "style", "noscript", "template"]):
        t.decompose()
    for t in soup.find_all(attrs={"hidden": True}):
        t.decompose()
    for t in soup.find_all(attrs={"aria-hidden": "true"}):
        t.decompose()
    for t in soup.find_all(style=re.compile(r"display\s*:\s*none", re.I)):
        t.decompose()
    candidates = []
    for el in soup.find_all(_BLOCK_TAGS):
        text = el.get_text("\n", strip=True)
        if 8 <= len(text) <= 800 and matches(text, match) and find_euro_amounts(text):
            candidates.append(el)
    cand_ids = {id(c) for c in candidates}
    minimal = []
    for el in candidates:
        if any(id(d) in cand_ids for d in el.find_all(_BLOCK_TAGS)):
            continue
        minimal.append(el.get_text("\n", strip=True))
    return minimal


# --------------------------------------------------------------------------
# Block-page detection
# --------------------------------------------------------------------------

BLOCK_STATUS = {403, 429, 503}
BLOCK_MARKERS = [
    "access denied", "just a moment", "pardon our interruption", "captcha",
    "attention required", "checking your browser", "are you a robot",
    "request blocked", "zugriff verweigert", "bot protection", "verify you are human",
    "bitte bestätigen sie, dass sie kein roboter sind", "ungewöhnliche aktivität",
    "challengepage", "sichere verbindung wird überprüft",
]
# a redirect to such a path is a bot check, whatever the page says
_BLOCK_URL = re.compile(r"challenge|captcha|/cdn-cgi/|/_incapsula_|/distil_", re.IGNORECASE)


def detect_block(http_status: int | None, title: str | None, text: str | None, has_price: bool = False,
                 final_url: str | None = None) -> bool:
    """True if the response looks like a bot wall / rate limit.

    The HTTP status and the page title are always checked. The body text is
    only checked when no price was found, so a shop page that merely mentions
    "captcha" in a newsletter form still counts as ok.
    """
    if http_status in BLOCK_STATUS:
        return True
    t = (title or "").lower()
    if any(m in t for m in BLOCK_MARKERS):
        return True
    if final_url and _BLOCK_URL.search(final_url) and not has_price:
        return True
    if has_price:
        return False
    body = (text or "").lower()[:5000]
    return any(m in body for m in BLOCK_MARKERS)


# --------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------

def visible_text(html_or_soup) -> str:
    soup = html_or_soup if isinstance(html_or_soup, BeautifulSoup) else BeautifulSoup(html_or_soup, "lxml")
    soup = BeautifulSoup(str(soup), "lxml")
    for t in soup(["script", "style", "noscript", "template"]):
        t.decompose()
    return soup.get_text("\n", strip=True)


def extract(
    html: str,
    *,
    page_type: str = "product",
    match: str | None = None,
    price_selector: str | None = None,
    listing_blocks: list[str] | None = None,
    page_text: str | None = None,
) -> Extraction:
    """Run the full extraction chain on rendered HTML.

    `listing_blocks` are tile texts collected in the browser (visible only);
    if None, they are derived from the HTML. `page_text` is the visible text
    of the page, used to find shipping costs on product pages.
    """
    soup = BeautifulSoup(html or "", "lxml")
    is_listing = page_type == "listing"

    result = (
        extract_jsonld(soup, match if is_listing else None)
        or extract_meta(soup)
        or extract_selector(soup, price_selector)
    )

    offers: list[dict] = []
    if is_listing:
        blocks = listing_blocks if listing_blocks is not None else listing_blocks_from_html(html, match)
        offers = parse_listing_blocks(blocks, match)
        if result is None and offers:
            best = min(offers, key=lambda o: o["price"])
            result = Extraction(price=best["price"], currency="EUR", shipping=best["shipping"], source="listing")

    if result is None:
        result = Extraction()
    result.offers = offers

    if result.price is not None and result.shipping is None and not is_listing:
        result.shipping = shipping_near_price(
            page_text if page_text is not None else visible_text(soup), result.price)
    if result.price is not None and not result.currency:
        result.currency = "EUR"
    return result
