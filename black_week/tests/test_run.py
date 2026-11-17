"""Tests for config loading, output files and (if a browser is available)
an end-to-end run against a local HTTP server - never the real internet."""

import asyncio
import csv
import json
import os
import shutil
import threading
from datetime import datetime, timezone
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

import run

FIXTURES = Path(__file__).parent / "fixtures"


def test_targets_yaml_is_valid():
    targets = run.load_targets(run.TARGETS_PATH)
    assert len(targets) == 15
    assert all(t["url"].startswith("https://") for t in targets)
    listings = [t for t in targets if t["type"] == "listing"]
    assert len(listings) == 3 and all(t["match"] == "SE 3" for t in listings)


def test_inactive_and_invalid_entries(tmp_path):
    p = tmp_path / "t.yaml"
    p.write_text("- {product: A, shop: S, url: 'https://a.de/', active: false}\n"
                 "- {product: B, shop: S, url: 'https://b.de/', type: listing, match: X}\n")
    assert [t["product"] for t in run.load_targets(p)] == ["B"]
    p.write_text("- {product: A, shop: S, url: 'https://a.de/', type: shop}\n")
    with pytest.raises(ValueError):
        run.load_targets(p)


def _result(**kw):
    target = {"product": "HomePod mini 2", "shop": "tink", "url": "https://www.tink.de/p/x", "type": "product"}
    r = run.empty_result(target, "ok")
    r.update(kw)
    return r


def test_write_results(tmp_path):
    results = [
        _result(price=1299.0, currency="EUR", shipping=4.99, source="jsonld", http_status=200),
        _result(status="blocked", http_status=403, shop="Shop | Pipe"),
    ]
    run_at = datetime(2026, 11, 28, 6, 15, tzinfo=timezone.utc)
    run.write_results(results, run_at, tmp_path)
    run.write_results(results, run_at, tmp_path)

    data = json.loads((tmp_path / "latest.json").read_text(encoding="utf-8"))
    assert data["generated_at"] == "2026-11-28T06:15:00Z"
    assert data["generated_at_berlin"] == "2026-11-28T07:15:00+01:00"
    assert set(data["results"][0]) >= {
        "product", "shop", "url", "status", "http_status", "price", "currency", "shipping",
        "availability", "source", "offers", "page_title", "fetched_at"}

    md = (tmp_path / "latest.md").read_text(encoding="utf-8")
    assert "Stand: 28.11.2026 07:15 Uhr (Europe/Berlin)" in md
    assert "| Produkt | Shop | Status | Preis | Versand | Quelle | URL |" in md
    assert "1.299,00 €" in md and "4,99 €" in md
    assert "Shop \\| Pipe" in md

    rows = list(csv.DictReader((tmp_path / "history.csv").open(encoding="utf-8")))
    assert len(rows) == 4                       # appended, header written once
    assert rows[0]["price"] == "1299.0"


# --------------------------------------------------------------------------
# End-to-end against a local server
# --------------------------------------------------------------------------

def _browser_available() -> bool:
    try:
        import playwright  # noqa: F401
    except ImportError:
        return False
    if os.environ.get("BLACK_WEEK_CHROMIUM"):
        return Path(os.environ["BLACK_WEEK_CHROMIUM"]).exists()
    return any((Path.home() / ".cache" / "ms-playwright").glob("chromium*")) or \
        bool(os.environ.get("PLAYWRIGHT_BROWSERS_PATH"))


class _Handler(SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        if self.path.startswith("/forbidden"):
            self.send_response(403)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(b"<html><head><title>403</title></head><body>Forbidden</body></html>")
            return
        if self.path.startswith("/slow"):
            import time
            time.sleep(3)
        return super().do_GET()


SOLARBANK_PAGE = """<!doctype html><html lang="de"><head><meta charset="utf-8">
<title>Anker SOLIX Solarbank 3 Pro 2.000 W Set | Baumarkt</title>
<script type="application/ld+json">{"@context":"https://schema.org","@type":"Product",
 "name":"Anker SOLIX Solarbank 3 Pro mit 2.000 W Solarmodulen",
 "offers":{"@type":"Offer","price":"1499.00","priceCurrency":"EUR","availability":"https://schema.org/InStock"}}</script>
</head><body><h1>Solarbank 3 Pro Set</h1><p>1.499,00 €</p></body></html>"""

WATCH_PAGE = """<!doctype html><html lang="de"><head><meta charset="utf-8">
<title>Apple Watch SE 3 40 mm (2025) gebraucht kaufen</title>
<script type="application/ld+json">{"@type":"Product","name":"Apple Watch SE 3 40 mm (2025)",
 "offers":{"@type":"AggregateOffer","lowPrice":"179.00","highPrice":"229.00","offerCount":4,"priceCurrency":"EUR"}}</script>
</head><body><h1>Apple Watch SE 3</h1></body></html>"""

DECOY_PAGE = SOLARBANK_PAGE.replace("Solarbank 3 Pro", "Solarbank 2 Plus").replace("2.000 W", "800 W")


def _site(tmp_path):
    import gzip
    site = tmp_path / "site"
    shutil.copytree(FIXTURES, site)
    (site / "slow").write_text("<html><title>slow</title></html>")
    (site / "p").mkdir()
    (site / "p" / "anker-solix-solarbank-3-pro-2000w-set.html").write_text(SOLARBANK_PAGE, encoding="utf-8")
    (site / "p" / "anker-solarbank-2-plus-800w.html").write_text(DECOY_PAGE, encoding="utf-8")
    (site / "p" / "apple-watch-se-3-40mm-2025.html").write_text(WATCH_PAGE, encoding="utf-8")
    return site


def _start(site):
    handler = lambda *a, **k: _Handler(*a, directory=str(site), **k)  # noqa: E731
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://127.0.0.1:{server.server_port}"


def _write_sitemaps(site, base):
    import gzip
    (site / "robots.txt").write_text(
        f"User-agent: *\nDisallow: /secret\nSitemap: {base}/sitemap_index.xml\n")
    (site / "sitemap_index.xml").write_text(
        '<?xml version="1.0"?><sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
        f"<sitemap><loc>{base}/sitemap-images.xml</loc></sitemap>"
        f"<sitemap><loc>{base}/sitemap-products-1.xml.gz</loc></sitemap></sitemapindex>")
    (site / "sitemap-images.xml").write_text("<urlset></urlset>")
    urls = ["/p/anker-solarbank-2-plus-800w.html", "/p/anker-solix-solarbank-3-pro-2000w-set.html",
            "/jsonld_offer.html", "/p/apple-watch-se-3-40mm-2025.html",
            "/p/gardena-gartenschlauch-20-m.html"]            # listed, but 404
    xml = '<?xml version="1.0"?><urlset>' + "".join(f"<url><loc>{base}{u}</loc></url>" for u in urls) + "</urlset>"
    (site / "sitemap-products-1.xml.gz").write_bytes(gzip.compress(xml.encode()))


@pytest.mark.skipif(not _browser_available(), reason="Playwright browser not installed")
def test_end_to_end_local(tmp_path, monkeypatch):
    site = _site(tmp_path)
    server, base = _start(site)
    _write_sitemaps(site, base)
    requested = []
    orig = _Handler.do_GET

    def logging_get(self):
        requested.append(self.path)
        return orig(self)
    monkeypatch.setattr(_Handler, "do_GET", logging_get)

    monkeypatch.setattr(run, "HOST_PAUSE_S", (0.0, 0.0))
    monkeypatch.setattr(run, "PRICE_WAIT_MS", 1000)
    monkeypatch.setattr(run, "NAV_TIMEOUT_MS", 1500)

    yaml_text = f"""
- {{product: Eve Thermo 5. Gen. 3er, shop: A, url: '{base}/jsonld_offer.html'}}
- {{product: LG StanbyME 2 Max, shop: A, url: '{base}/jsonld_aggregate.html'}}
- {{product: Apple Watch SE 3, shop: A, type: listing, match: SE 3, url: '{base}/listing.html'}}
- {{product: Blocked Product, shop: A, url: '{base}/blocked.html'}}
- {{product: Forbidden Product, shop: A, url: '{base}/forbidden'}}
- {{product: Robots Product, shop: A, url: '{base}/secret/page.html'}}
- {{product: Venjakob Kalea, shop: A, url: '{base}/no_price.html'}}
- {{product: HomePod mini 2, shop: A, url: '{base}/does-not-exist.html'}}
- {{product: Slow Product, shop: A, url: '{base}/slow'}}
- {{product: Anker Solarbank 3 Pro 2.000 W, shop: A, url: '{base}/p/old-solarbank'}}
- {{product: Anker Solarbank 3 Pro 2.000 W, shop: B, site: '{base}'}}
- {{product: Apple Watch SE 3, shop: C, type: listing, match: SE 3, url: '{base}/no_price.html'}}
- {{product: Gardena Gartenschlauch 20 m, shop: A, url: '{base}/p/gardena-schlauch-alt.html'}}
"""
    tfile = tmp_path / "targets.yaml"
    tfile.write_text(yaml_text)
    targets = run.load_targets(tfile)
    try:
        results = asyncio.run(run.fetch_all(targets, log=lambda *_: None))
    finally:
        server.shutdown()

    by = {(r["product"], r["shop"]): r for r in results}
    g = lambda name, shop="A": by[(name, shop)]  # noqa: E731
    assert g("Eve Thermo 5. Gen. 3er")["status"] == "ok" and g("Eve Thermo 5. Gen. 3er")["price"] == 209.99
    assert g("Eve Thermo 5. Gen. 3er")["shipping"] == 4.95 and g("Eve Thermo 5. Gen. 3er")["url_check"] == "ok"
    assert g("LG StanbyME 2 Max")["price"] == 1049.0 and g("LG StanbyME 2 Max")["offer_count"] == 17
    listing = g("Apple Watch SE 3")
    assert listing["source"] == "listing" and len(listing["offers"]) == 2
    assert all("versteckt" not in o["title"] for o in listing["offers"])
    assert g("Blocked Product")["status"] == "blocked" and g("Blocked Product")["url_check"] == "not_checked"
    assert g("Forbidden Product")["status"] == "blocked" and g("Forbidden Product")["http_status"] == 403
    assert g("Robots Product")["status"] == "robots"
    assert g("Venjakob Kalea")["status"] == "no_price" and g("Venjakob Kalea")["url_check"] == "broken"
    assert g("HomePod mini 2")["status"] == "error" and g("HomePod mini 2")["http_status"] == 404
    assert g("HomePod mini 2")["url_check"] == "broken" and "no replacement" in g("HomePod mini 2")["note"]
    assert g("Slow Product")["status"] == "timeout"

    # moved product: 404 -> found via gzipped sitemap -> verified -> updated
    moved = g("Anker Solarbank 3 Pro 2.000 W")
    assert moved["url_check"] == "updated", moved
    assert moved["url"] == f"{base}/p/anker-solix-solarbank-3-pro-2000w-set.html"
    assert moved["previous_url"] == f"{base}/p/old-solarbank"
    assert moved["status"] == "ok" and moved["price"] == 1499.0
    # product defined only by shop site, no URL at all
    fresh = g("Anker Solarbank 3 Pro 2.000 W", "B")
    assert fresh["url_check"] == "updated" and fresh["price"] == 1499.0
    # decoy (Solarbank 2 Plus) and image sitemap never opened
    assert "/p/anker-solarbank-2-plus-800w.html" not in requested
    assert "/sitemap-images.xml" not in requested
    assert requested.count("/sitemap-products-1.xml.gz") == 1      # cached within a run
    assert all(r["fetched_at"].endswith("Z") for r in results)

    # outdated listing (keyword not on page) -> replaced by a matching page
    lst = g("Apple Watch SE 3", "C")
    assert lst["url_check"] == "updated" and lst["url"].endswith("/p/apple-watch-se-3-40mm-2025.html")
    assert lst["price"] == 179.0 and lst["status"] == "ok"
    # shop answers 404 even for URLs from its own sitemap -> reported as blocked
    hose = g("Gardena Gartenschlauch 20 m")
    assert hose["status"] == "blocked" and "own sitemap" in hose["note"], hose

    # final update: state file keeps the new URL for the next run
    state = run.update_url_state({}, targets, results)
    key = "Anker Solarbank 3 Pro 2.000 W | A"
    assert state[key]["url"] == moved["url"] and state[key]["seed_url"] == f"{base}/p/old-solarbank"
    targets2 = run.load_targets(tfile)
    run.apply_url_state(targets2, state)
    assert [t for t in targets2 if t["shop"] == "A" and t["product"].startswith("Anker")][0]["url"] == moved["url"]
