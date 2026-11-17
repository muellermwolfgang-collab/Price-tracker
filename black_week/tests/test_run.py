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


@pytest.mark.skipif(not _browser_available(), reason="Playwright browser not installed")
def test_end_to_end_local(tmp_path, monkeypatch):
    site = tmp_path / "site"
    shutil.copytree(FIXTURES, site)
    (site / "robots.txt").write_text("User-agent: *\nDisallow: /secret\n")
    (site / "slow").write_text("<html><title>slow</title></html>")
    handler = lambda *a, **k: _Handler(*a, directory=str(site), **k)  # noqa: E731
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_port}"

    monkeypatch.setattr(run, "HOST_PAUSE_S", (0.0, 0.0))
    monkeypatch.setattr(run, "PRICE_WAIT_MS", 1000)
    monkeypatch.setattr(run, "NAV_TIMEOUT_MS", 1500)

    def t(name, path, **kw):
        return {"product": name, "shop": "local", "url": base + path, "type": "product",
                "match": None, "price_selector": None, **kw}

    targets = [
        t("offer", "/jsonld_offer.html"),
        t("aggregate", "/jsonld_aggregate.html"),
        t("listing", "/listing.html", type="listing", match="SE 3"),
        t("blocked-title", "/blocked.html"),
        t("blocked-403", "/forbidden"),
        t("robots", "/secret/page.html"),
        t("no-price", "/no_price.html"),
        t("missing", "/does-not-exist.html"),
        t("timeout", "/slow"),
    ]
    try:
        results = asyncio.run(run.fetch_all(targets, log=lambda *_: None))
    finally:
        server.shutdown()

    by = {r["product"]: r for r in results}
    assert by["offer"]["status"] == "ok" and by["offer"]["price"] == 209.99
    assert by["offer"]["shipping"] == 4.95 and by["offer"]["http_status"] == 200
    assert by["aggregate"]["price"] == 1049.0 and by["aggregate"]["offer_count"] == 17
    assert by["listing"]["source"] == "listing" and len(by["listing"]["offers"]) == 2
    assert all("versteckt" not in o["title"] for o in by["listing"]["offers"])
    assert by["blocked-title"]["status"] == "blocked"
    assert by["blocked-403"]["status"] == "blocked" and by["blocked-403"]["http_status"] == 403
    assert by["robots"]["status"] == "robots"
    assert by["no-price"]["status"] == "no_price"
    assert by["missing"]["status"] == "error" and by["missing"]["http_status"] == 404
    assert by["timeout"]["status"] == "timeout"
    assert all(r["fetched_at"].endswith("Z") for r in results)
