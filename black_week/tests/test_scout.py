"""Tests for the scout (shop search per product)."""

import asyncio
import json
import shutil

import pytest

import discover as d
import run
import scout
from test_run import FIXTURES, SOLARBANK_PAGE, _browser_available, _Handler, _start


def test_strict_match_rejects_lookalikes():
    t = {"product": "HomePod mini 2", "keywords": []}
    assert d.page_matches_strict(t, "Apple HomePod mini (2. Generation)", None)
    assert not d.page_matches_strict(t, "Mini-Kühlschrank 2 Türen", None)       # 2 of 3 words
    assert not d.page_matches_strict(t, "Apple HomePod mini", None)             # 1st generation
    t2 = {"product": "Anker Solarbank 3 Pro", "keywords": []}
    assert not d.page_matches_strict(t2, "Solarbank 3 Pro Halterung", "Zubehör")  # brand missing


def test_in_scope():
    assert d.in_scope("https://www.lg.com/de/tv/x", "https://www.lg.com/de")
    assert not d.in_scope("https://www.lg.com/uk/tv/x", "https://www.lg.com/de")
    assert d.in_scope("https://www.toom.de/p/x", "https://toom.de")
    assert not d.in_scope("https://static.toom.de/p/x", "https://toom.de")


def test_coverage_includes_inactive_and_variants(tmp_path):
    p = tmp_path / "targets.yaml"
    p.write_text("- {product: Apple Watch SE 3 40 mm, shop: refurbed, url: 'https://www.refurbed.de/p/x'}\n"
                 "- {product: HomePod mini 2, shop: OTTO, site: otto.de, active: false}\n")
    cov = scout.existing_coverage(p)
    watch, homepod = {"product": "Apple Watch SE 3"}, {"product": "HomePod mini 2"}
    assert scout.is_covered(watch, {"site": "https://refurbed.de"}, cov)
    assert scout.is_covered(homepod, {"site": "https://www.otto.de"}, cov)      # switched off by you
    assert not scout.is_covered(homepod, {"site": "https://www.refurbed.de"}, cov)


def test_add_product_and_targets_append_keep_comments(tmp_path):
    prod = tmp_path / "products.yaml"
    prod.write_text("# my comment\n- product: HomePod mini 2\n  active: true\n")
    assert scout.add_product("Dyson V15 Detect", ["V15"], prod)
    assert not scout.add_product("dyson v15 detect", [], prod)                  # already there
    text = prod.read_text()
    assert text.startswith("# my comment") and "Dyson V15 Detect" in text
    assert [p["product"] for p in scout.load_products(prod)] == ["HomePod mini 2", "Dyson V15 Detect"]

    targets = tmp_path / "targets.yaml"
    targets.write_text("# header stays\n- product: A\n  shop: S\n  url: https://s.de/a\n")
    report = [{"product": "Dyson V15: Detect", "shop": "OTTO", "status": "added", "url": "https://www.otto.de/p/v15"},
              {"product": "B", "shop": "OTTO", "status": "not_found"}]
    entries = scout.new_target_entries(report, [{"shop": "OTTO", "site": "https://www.otto.de"}])
    scout._append_yaml_entries(targets, entries, "found by scout")
    assert targets.read_text().startswith("# header stays")
    loaded = run.load_targets(targets)
    assert [t["product"] for t in loaded] == ["A", "Dyson V15: Detect"]
    assert loaded[1]["url"] == "https://www.otto.de/p/v15"


def test_resolve_shops(tmp_path):
    shops = tmp_path / "shops.yaml"
    shops.write_text("- {shop: OTTO, site: www.otto.de}\n- {shop: toom, site: toom.de}\n")
    catalog = scout.load_shops(shops)
    assert [s["shop"] for s in scout.resolve_shops("", catalog, shops)] == ["OTTO", "toom"]
    assert [s["shop"] for s in scout.resolve_shops("otto", catalog, shops)] == ["OTTO"]
    chosen = scout.resolve_shops("toom.de, www.cyberport.de", catalog, shops)
    assert [s["site"] for s in chosen] == ["https://toom.de", "https://www.cyberport.de"]
    assert "cyberport" in shops.read_text()                                     # remembered


def test_real_config_files_load():
    assert scout.load_products() and scout.load_shops()


FRIDGE_PAGE = """<!doctype html><html><head><meta charset="utf-8"><title>Mini-Kühlschrank 2 Türen</title>
<script type="application/ld+json">{"@type":"Product","name":"Mini-Kühlschrank 2 Türen",
"offers":{"@type":"Offer","price":"89.00","priceCurrency":"EUR"}}</script></head><body></body></html>"""


@pytest.mark.skipif(not _browser_available(), reason="Playwright browser not installed")
def test_scout_end_to_end_local(tmp_path, monkeypatch):
    import gzip
    site = tmp_path / "site"
    shutil.copytree(FIXTURES, site)
    (site / "p").mkdir()
    (site / "p" / "anker-solix-solarbank-3-pro-2000w-set.html").write_text(SOLARBANK_PAGE, encoding="utf-8")
    (site / "p" / "mini-kuehlschrank-2-tueren.html").write_text(FRIDGE_PAGE, encoding="utf-8")
    server, base = _start(site)
    (site / "robots.txt").write_text(f"User-agent: *\nSitemap: {base}/sitemap.xml.gz\n")
    urls = ["/p/anker-solix-solarbank-3-pro-2000w-set.html", "/p/mini-kuehlschrank-2-tueren.html"]
    xml = "<urlset>" + "".join(f"<url><loc>{base}{u}</loc></url>" for u in urls) + "</urlset>"
    (site / "sitemap.xml.gz").write_bytes(gzip.compress(xml.encode()))
    monkeypatch.setattr(run, "HOST_PAUSE_S", (0.0, 0.0))
    monkeypatch.setattr(run, "PRICE_WAIT_MS", 1000)

    products = [{"product": "Anker Solarbank 3 Pro", "keywords": []},
                {"product": "HomePod mini 2", "keywords": []},
                {"product": "Eve Thermo 5. Gen. 3er", "keywords": []}]
    shops = [{"shop": "Local", "site": base}]
    coverage = [("127.0.0.1", set(d.tokens("Eve Thermo 5. Gen. 3er")))]      # already listed
    try:
        report = asyncio.run(scout.scout(products, shops, coverage, log=lambda *_: None))
    finally:
        server.shutdown()

    by = {r["product"]: r for r in report}
    assert by["Anker Solarbank 3 Pro"]["status"] == "added"
    assert by["Anker Solarbank 3 Pro"]["url"] == f"{base}/p/anker-solix-solarbank-3-pro-2000w-set.html"
    assert by["Anker Solarbank 3 Pro"]["price"] == 1499.0
    assert by["HomePod mini 2"]["status"] == "not_found"                        # fridge rejected
    assert by["Eve Thermo 5. Gen. 3er"]["status"] == "listed"
    md = scout.render_report(report, run.datetime.now(run.timezone.utc))
    assert "➕ neu hinzugefügt" in md and "Anker Solarbank 3 Pro bei Local" in md


@pytest.mark.parametrize("product, name", [
    # the four wrong finds of the first live scout run
    ("Apple Watch SE 3", "caseonline RIB Ersatzarmband Apple Watch SE 3 40mm weiß"),
    ("Apple Watch SE 3", "caseonline RSF Ersatzarmband Apple Watch SE 3 40mm rosa"),
    ("HomePod mini 2", "upscreen entspiegelt matte Schutzfolie für Apple HomePod mini 2"),
    ("HomePod 2. Gen.", "Apple HomePod mini (2. Gen)"),
    ("Apple Watch SE 3", "Panzerglas Displayschutz kompatibel mit Apple Watch SE 3"),
])
def test_accessories_and_other_models_rejected(product, name):
    t = {"product": product, "keywords": []}
    assert not d.page_matches_strict(t, name, None)
    assert not d.page_matches(t, name, None)


@pytest.mark.parametrize("product, name", [
    ("Apple Watch SE 3", "Apple Watch SE 3 (2025) GPS 40 mm Aluminium"),
    ("HomePod mini 2", "Apple HomePod mini (2. Generation) Mitternacht"),
    ("HomePod 2. Gen.", "Apple HomePod (2. Generation) weiß"),
    ("Anker Solarbank 3 Pro", "ANKER SOLIX Solarbank 3 E2700 Pro mit 910W PV"),
    ("Eve Thermo 5. Gen. 3er", "Eve Thermo (5. Gen.) Matter Heizkörperthermostat 3er-Set kabellos"),
])
def test_real_products_accepted(product, name):
    assert d.page_matches_strict({"product": product, "keywords": []}, name, None)


def test_accessory_product_itself_is_fine():
    t = {"product": "Apple Sport Loop Armband 41 mm", "keywords": []}
    assert d.page_matches_strict(t, "Apple Sport Loop Armband 41 mm Blau", None)


def test_price_plausibility(tmp_path):
    latest = tmp_path / "latest.json"
    latest.write_text(json.dumps({"results": [
        {"product": "HomePod mini 2", "status": "ok", "price": 168.95},
        {"product": "HomePod mini 2", "status": "ok", "price": 149.63},
        {"product": "Apple Watch SE 3 40 mm", "status": "ok", "price": 209.0},
        {"product": "LG StanbyME 2 Max", "status": "blocked", "price": None},
    ]}))
    known = scout.known_prices(latest)
    assert not scout.plausible("HomePod mini 2", 8.49, known)[0]          # Schutzfolie
    assert scout.plausible("HomePod mini 2", 139.0, known)[0]
    assert not scout.plausible("Apple Watch SE 3", 23.90, known)[0]       # Ersatzarmband
    assert scout.plausible("LG StanbyME 2 Max", 999.0, known)[0]          # nothing known yet
