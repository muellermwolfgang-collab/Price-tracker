"""Offline tests for the price extraction (no network, no browser)."""

from pathlib import Path

import pytest

import extract as ex

FIXTURES = Path(__file__).parent / "fixtures"


def load(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


@pytest.mark.parametrize("raw, expected", [
    ("1.299,00 €", 1299.0),
    ("209,99 €", 209.99),
    ("ab 164,25 €", 164.25),
    ("€ 1.049,00", 1049.0),
    ("99,- €", 99.0),
    ("99,– €", 99.0),
    ("1.299 €", 1299.0),
    ("1299.00", 1299.0),
    ("209.99", 209.99),
    ("1,299.00", 1299.0),
    ("12.345.678,90 €", 12345678.9),
    ("  279  ", 279.0),
    (279, 279.0),
    (4.95, 4.95),
    ("", None),
    ("kein Preis", None),
    (None, None),
])
def test_parse_price(raw, expected):
    assert ex.parse_price(raw) == expected


def test_find_euro_amounts_german_text():
    vals = [v for v, _, _ in ex.find_euro_amounts("statt 1.299,00 € jetzt ab 999,- € oder € 49,99")]
    assert vals == [1299.0, 999.0, 49.99]


def test_offer_prices_skip_shipping_and_rates():
    text = "Apple Watch SE 3\n189,00 €\nzzgl. Versand 4,99 €\nab 9,99 €/Monat"
    assert ex.offer_prices(text) == [189.0]


@pytest.mark.parametrize("text, expected", [
    ("zzgl. 4,99 € Versand", 4.99),
    ("Versand: 5,95 €", 5.95),
    ("Versandkosten 3,90 €", 3.9),
    ("Versandkostenfrei", 0.0),
    ("Kostenloser Versand", 0.0),
    ("Kostenloser Versand ab 50 €", None),
    ("Preis 199,00 €", None),
])
def test_find_shipping(text, expected):
    assert ex.find_shipping(text) == expected


def test_jsonld_offer():
    r = ex.extract(load("jsonld_offer.html"))
    assert r.source == "jsonld"
    assert r.price == 209.99
    assert r.currency == "EUR"
    assert r.availability == "InStock"
    assert r.shipping == 4.95


def test_jsonld_aggregate_offer_in_graph():
    r = ex.extract(load("jsonld_aggregate.html"))
    assert r.source == "jsonld"
    assert r.price == 1049.0
    assert r.price_high == 1299.0
    assert r.offer_count == 17
    assert r.currency == "EUR"


def test_jsonld_list_of_offers_takes_cheapest():
    html = """<script type="application/ld+json">[{"@type":"Product","name":"X",
      "offers":[{"@type":"Offer","price":"199,00","priceCurrency":"EUR"},
                {"@type":"Offer","priceSpecification":{"price":149.5,"priceCurrency":"EUR"}}]}]</script>"""
    r = ex.extract(html)
    assert (r.price, r.source) == (149.5, "jsonld")


def test_jsonld_product_page_uses_main_product_not_cheaper_accessory():
    html = """<script type="application/ld+json">{"@type":"Product","name":"HomePod 2",
      "offers":{"@type":"Offer","price":"279.00","priceCurrency":"EUR"},
      "isRelatedTo":[{"@type":"Product","name":"Kabel","offers":{"@type":"Offer","price":"9.99"}}]}</script>
      <script type="application/ld+json">{"@type":"Product","name":"Wandhalterung",
      "offers":{"@type":"Offer","price":"19.99","priceCurrency":"EUR"}}</script>"""
    assert ex.extract(html).price == 279.0


def test_jsonld_broken_block_is_ignored():
    html = """<script type="application/ld+json">{ broken json </script>
    <meta property="og:price:amount" content="12,50"><meta property="og:price:currency" content="EUR">"""
    r = ex.extract(html)
    assert (r.price, r.source, r.currency) == (12.5, "meta", "EUR")


def test_meta_tags_and_shipping_from_text():
    r = ex.extract(load("meta_tags.html"))
    assert r.source == "meta"
    assert r.price == 99.0
    assert r.currency == "EUR"
    assert r.shipping == 4.99


def test_itemprop_price_german_format():
    r = ex.extract(load("itemprop.html"))
    assert r.source == "meta"
    assert r.price == 1299.0
    assert r.availability == "OutOfStock"
    assert r.shipping == 0.0


def test_price_selector_fallback():
    html = load("selector_only.html")
    assert ex.extract(html).price is None
    r = ex.extract(html, price_selector=".product-price .value")
    assert (r.price, r.source, r.currency) == (1299.0, "selector", "EUR")


def test_invalid_selector_does_not_crash():
    assert ex.extract(load("selector_only.html"), price_selector="::::").price is None


def test_listing_offers_from_html():
    r = ex.extract(load("listing.html"), page_type="listing", match="SE 3")
    assert r.source == "listing"
    assert r.price == 164.25
    titles = [o["title"] for o in r.offers]
    assert titles == ["Apple Watch SE 3 40 mm GPS Aluminium", "Apple Watch SE 3 44 mm GPS + Cellular"]
    assert r.offers[0]["condition"] == "Sehr gut"
    assert r.offers[1]["condition"] == "Exzellent"
    assert r.offers[1]["price"] == 209.99
    assert r.offers[1]["shipping"] == 4.99


def test_listing_blocks_from_browser_text():
    blocks = [
        "Apple Watch SE 3 (2025) 40 mm\nHervorragend\nab 179,00 €",
        "Apple Watch SE 3 (2025) 40 mm\nHervorragend\nab 179,00 €",   # duplicate tile
        "Apple Watch SE3 44 mm\nWie neu\n229,00 €",
        "Apple Watch Ultra\n599,00 €",
    ]
    offers = ex.parse_listing_blocks(blocks, "SE 3")
    assert [(o["price"], o["condition"]) for o in offers] == [(179.0, "Hervorragend"), (229.0, "Wie neu")]


def test_listing_jsonld_filtered_by_match():
    html = """<script type="application/ld+json">{"@type":"ItemList","itemListElement":[
      {"@type":"Product","name":"Apple Watch SE (2. Gen.)","offers":{"@type":"Offer","price":"99.00","priceCurrency":"EUR"}},
      {"@type":"Product","name":"Apple Watch SE 3 40mm","offers":{"@type":"Offer","price":"189.00","priceCurrency":"EUR"}}]}</script>"""
    r = ex.extract(html, page_type="listing", match="SE 3", listing_blocks=[])
    assert (r.price, r.source) == (189.0, "jsonld")


@pytest.mark.parametrize("text, expected", [
    ("Apple Watch SE 3", True), ("apple watch se3", True), ("Watch SE-3 GPS", True),
    ("Apple Watch SE 30", False), ("Apple Watch Series 3", False), ("Apple Watch SE", False),
])
def test_match_keyword(text, expected):
    assert ex.matches(text, "SE 3") is expected


def test_blocked_page_detected():
    html = load("blocked.html")
    r = ex.extract(html)
    assert r.price is None
    assert ex.detect_block(200, "Just a moment...", ex.visible_text(html))


def test_pardon_our_interruption_detected_in_body():
    html = load("pardon.html")
    assert ex.detect_block(200, "MediaMarkt", ex.visible_text(html), has_price=False)


@pytest.mark.parametrize("status", [403, 429, 503])
def test_blocked_http_status(status):
    assert ex.detect_block(status, "Shop", "", has_price=True)


def test_captcha_mention_with_price_is_not_blocked():
    html = load("captcha_mention_with_price.html")
    r = ex.extract(html)
    assert r.price == 279.0
    assert not ex.detect_block(200, "HomePod 2 | Shop", ex.visible_text(html), has_price=True)


def test_no_price_page():
    html = load("no_price.html")
    r = ex.extract(html)
    assert r.price is None and r.source is None
    assert not ex.detect_block(200, "Esszimmerstühle | moebel.de", ex.visible_text(html))


def test_shipping_only_near_price():
    page = ("Filter: versandkostenfrei\n" + "x " * 400 +
            "\nHomePod mini 2\n99,00 €\ninkl. MwSt.\n" + "y " * 400 + "\nKostenloser Versand")
    assert ex.shipping_near_price(page, 99.0) is None
    near = "HomePod mini 2\n99,00 €\nzzgl. 4,99 € Versand"
    assert ex.shipping_near_price(near, 99.0) == 4.99
    assert ex.shipping_near_price("Preis 99,00 €\nVersandkostenfrei", 99.0) == 0.0
    assert ex.shipping_near_price("kein passender Preis", 99.0) is None
