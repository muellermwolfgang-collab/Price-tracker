"""Offline tests for URL maintenance (matching, sitemaps, URL check, state)."""

import gzip

import pytest

import discover as d
import run


def target(product, **kw):
    return {"product": product, "shop": "S", "url": "https://s.de/x", "seed_url": "https://s.de/x",
            "site": "https://s.de", "type": "product", "match": None, "price_selector": None,
            "keywords": [], **kw}


def test_tokens_normalise():
    assert d.tokens("Anker Solarbank 3 Pro 2.000 W") == ["anker", "solarbank", "3", "pro", "2000"]
    assert d.tokens("Heizkörperthermostat 3er-Set") == ["heizkoerperthermostat", "3", "er", "set"]
    assert d.tokens("/p/anker-solix-solarbank-3-pro-mit-910w-pv.html") == \
        ["anker", "solix", "solarbank", "3", "pro", "910", "pv"]


@pytest.mark.parametrize("product, text, minimum", [
    ("HomePod 2. Gen.", "Apple MQJ73D/A HomePod (2. Generation) - Preisvergleich", 1.0),
    ("Eve Thermo 5. Gen. 3er", "Eve Thermo Matter (5. Gen) - Heizkörperthermostat - 3er-Set kaufen", 1.0),
    ("Anker Solarbank 3 Pro 910 W", "ANKER SOLIX Solarbank 3 Pro mit 910W PV Balkonkraftwerk", 1.0),
    ("Apple Watch SE 3 40 mm", "Apple Watch SE 3 40 mm 2025 - Smart, leicht und vielseitig", 1.0),
])
def test_real_titles_match(product, text, minimum):
    assert d.match_score(d.tokens(product), text) >= minimum


def test_numbers_must_match_exactly():
    assert d.match_score(["3"], "Apple Watch SE 30") == 0.0
    assert d.match_score(["gen"], "2. Generation") == 1.0


def test_keywords_required():
    t = target("Anker Solarbank 3 Pro", keywords=["2.000 W"])
    assert not d.page_matches(t, "Anker Solarbank 3 Pro 800 W", None)
    assert d.page_matches(t, "Anker Solarbank 3 Pro Set 2000 W", None)


def test_parse_sitemap_plain_and_gzip():
    xml = (b'<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
           b"<url><loc>https://s.de/p/a?x=1&amp;y=2</loc></url>"
           b"<url><loc><![CDATA[https://s.de/p/b]]></loc></url></urlset>")
    assert d.parse_sitemap(xml) == (False, ["https://s.de/p/a?x=1&y=2", "https://s.de/p/b"])
    assert d.parse_sitemap(gzip.compress(xml))[1] == ["https://s.de/p/a?x=1&y=2", "https://s.de/p/b"]
    idx = b'<sitemapindex><sitemap><loc>https://s.de/sitemap-products.xml</loc></sitemap></sitemapindex>'
    assert d.parse_sitemap(idx) == (True, ["https://s.de/sitemap-products.xml"])


def test_rank_sitemaps():
    urls = ["https://s.de/sitemap-images-1.xml", "https://s.de/sitemap-blog.xml",
            "https://s.de/sitemap-1.xml", "https://s.de/sitemap-products-2.xml.gz"]
    assert d.rank_sitemaps(urls) == ["https://s.de/sitemap-products-2.xml.gz", "https://s.de/sitemap-1.xml"]


def test_score_urls_prefers_best_match():
    t = target("Anker Solarbank 3 Pro 2.000 W")
    urls = [
        "https://s.de/p/anker-solarbank-2-plus/1",
        "https://s.de/p/solarmodul-set-4-x-500-w-mit-solarbank-3-e2700-pro-und-smart-meter/10520584",
        "https://s.de/p/anker-solix-solarbank-3-pro-2000-w/1",
        "https://s.de/p/gartenschlauch/2",
    ]
    ranked = d.score_urls(urls, t)
    assert [u for _, u in ranked] == urls[2:3] + urls[1:2]


def _res(status, http=200, name=None, title=None):
    return {"status": status, "http_status": http, "_name": name, "page_title": title}


@pytest.mark.parametrize("res, verdict", [
    (_res("ok", name="Anker Solarbank 3 Pro 2.000 W"), "ok"),
    (_res("ok", name="Gartenschlauch 20 m", title="Gartenschlauch | Shop"), "broken"),
    (_res("no_price", title="Anker Solarbank 3 Pro"), "broken"),
    (_res("error", 404), "broken"),
    (_res("error", 410), "broken"),
    (_res("blocked", 403), "not_checked"),
    (_res("robots", None), "not_checked"),
    (_res("timeout", None), "not_checked"),
    (_res("error", None), "not_checked"),
    (_res("error", 500), "not_checked"),
])
def test_check_url(res, verdict):
    assert run.check_url(target("Anker Solarbank 3 Pro 2.000 W"), res)[0] == verdict


def test_check_url_listing_not_judged_by_name():
    t = target("Apple Watch SE 3", type="listing", match="SE 3")
    assert run.check_url(t, _res("ok", title="Smartwatches kaufen"))[0] == "ok"
    assert run.check_url(t, _res("no_price", title="Apple Watch kaufen"))[0] == "broken"
    assert run.check_url(t, _res("error", 404))[0] == "broken"


def test_url_state_roundtrip_and_seed_change():
    t = target("P")
    r = {"url": "https://s.de/new", "url_check": "updated", "fetched_at": "2026-11-17T12:00:00Z"}
    state = run.update_url_state({}, [t], [r])
    assert state["P | S"]["url"] == "https://s.de/new"
    assert state["P | S"]["previous_urls"] == ["https://s.de/x"]

    t2 = target("P")
    run.apply_url_state([t2], state)
    assert t2["url"] == "https://s.de/new"

    # user edits targets.yaml -> their new URL wins over the stored one
    t3 = target("P", url="https://s.de/manual", seed_url="https://s.de/manual")
    run.apply_url_state([t3], state)
    assert t3["url"] == "https://s.de/manual"

    broken = {"url": "https://s.de/new", "url_check": "broken", "fetched_at": "2026-11-18T06:00:00Z"}
    state2 = run.update_url_state(state, [t2], [broken])
    assert state2["P | S"]["url"] == "https://s.de/new"
    assert state2["P | S"]["broken_since"] == "2026-11-18T06:00:00Z"


def test_target_without_url_needs_site(tmp_path):
    p = tmp_path / "t.yaml"
    p.write_text("- {product: A, shop: S, site: toom.de}\n")
    t = run.load_targets(p)[0]
    assert t["url"] is None and t["site"] == "https://toom.de"
    p.write_text("- {product: A, shop: S}\n")
    with pytest.raises(ValueError):
        run.load_targets(p)
