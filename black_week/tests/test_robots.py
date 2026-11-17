"""Offline tests for robots.txt handling (RFC 9309)."""

from robots import RobotsRules, rules_from_response

UA = "PriceTracker"

SAMPLE = """
User-agent: *
Disallow: /checkout/
Disallow: /*?filter=
Disallow: /*.pdf$
Allow: /checkout/info

User-agent: BadBot
Disallow: /
"""


def test_wildcards_and_longest_match():
    r = RobotsRules(SAMPLE)
    assert r.can_fetch(UA, "https://shop.de/p/apple-watch")
    assert not r.can_fetch(UA, "https://shop.de/checkout/cart")
    assert r.can_fetch(UA, "https://shop.de/checkout/info")
    assert not r.can_fetch(UA, "https://shop.de/kaufen?filter=se3")
    assert not r.can_fetch(UA, "https://shop.de/doc/manual.pdf")
    assert r.can_fetch(UA, "https://shop.de/doc/manual.pdf?x=1")


def test_specific_group_overrides_star():
    r = RobotsRules(SAMPLE + "\nUser-agent: PriceTracker\nDisallow: /p/\n")
    assert not r.can_fetch(UA, "https://shop.de/p/apple-watch")
    assert r.can_fetch(UA, "https://shop.de/checkout/cart")   # star group no longer applies


def test_other_bot_group_does_not_apply():
    r = RobotsRules("User-agent: BadBot\nDisallow: /\n")
    assert r.can_fetch(UA, "https://shop.de/anything")


def test_empty_disallow_allows_all():
    assert RobotsRules("User-agent: *\nDisallow:\n").can_fetch(UA, "https://shop.de/x")


def test_query_string_rule():
    r = RobotsRules("User-agent: *\nDisallow: /*data-sheet=\n")
    assert not r.can_fetch(UA, "https://www.moebel.de/essen/stuehle?data-sheet=abc")
    assert r.can_fetch(UA, "https://www.moebel.de/essen/stuehle")


def test_fetch_outcomes():
    assert rules_from_response(404, None).can_fetch(UA, "https://x.de/a")
    assert rules_from_response(403, None).can_fetch(UA, "https://x.de/a")
    assert not rules_from_response(500, None).can_fetch(UA, "https://x.de/a")
    assert not rules_from_response(None, None).can_fetch(UA, "https://x.de/a")
    assert not rules_from_response(200, "User-agent: *\nDisallow: /\n").can_fetch(UA, "https://x.de/a")


def test_unavailable_is_flagged():
    assert rules_from_response(None, None).unavailable
    assert rules_from_response(503, None).unavailable
    assert rules_from_response(429, None).unavailable
    assert rules_from_response(200, "User-agent: *\nDisallow: /\n").unavailable is None
