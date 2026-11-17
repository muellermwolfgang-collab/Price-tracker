"""
URL maintenance for black_week: find a new product URL when the stored one
is gone (404, no price any more, or the page shows a different product).

How a replacement is found - without search engines, logins or tricks:
  1. Read the shop's sitemaps. They are listed in robots.txt ("Sitemap:")
     and published precisely so that crawlers can find product pages.
  2. Score every sitemap URL by how many words of the product name appear
     in its path (e.g. ".../anker-solix-solarbank-3-pro-...").
  3. The caller then opens the best few candidates and keeps the first one
     that has a price and whose product name matches (see `name_score`).

The pure helpers (tokens, scoring, sitemap parsing) are unit-tested offline;
`collect_candidates` does the network part through the Fetcher, so it obeys
the same robots.txt and per-host pacing rules as everything else.
"""

from __future__ import annotations

import gzip
import heapq
import re
from urllib.parse import unquote, urlsplit

# --------------------------------------------------------------------------
# Tokens and matching
# --------------------------------------------------------------------------

_UMLAUTS = str.maketrans({"ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss", "é": "e", "è": "e"})
STOPWORDS = {
    "und", "mit", "der", "die", "das", "den", "dem", "fuer", "for", "the", "and", "of", "von",
    "in", "im", "zu", "ein", "eine", "inkl", "kaufen", "online", "shop", "neu", "new", "de",
    "html", "htm", "php", "www", "com", "p", "product", "produkt", "products", "artikel",
}


def tokens(text: str | None) -> list[str]:
    """Normalised words: lower case, umlauts spelled out, "2.000" -> "2000",
    letters and digits split ("910W" -> "910", "w"), stop words and single
    letters dropped."""
    if not text:
        return []
    t = unquote(str(text)).lower().translate(_UMLAUTS)
    t = re.sub(r"(?<=\d)[.,](?=\d{3}\b)", "", t)          # thousands separator
    t = re.sub(r"(?<=[a-z])(?=\d)|(?<=\d)(?=[a-z])", " ", t)
    out = []
    for w in re.split(r"[^a-z0-9]+", t):
        if not w or w in STOPWORDS or (len(w) == 1 and w.isalpha()):
            continue
        out.append(w)
    return out


def _token_found(tok: str, haystack: set[str]) -> bool:
    if tok in haystack:
        return True
    if tok.isdigit() or len(tok) < 3:
        return False
    # "gen" matches "generation", "thermo" matches "thermostat"
    return any(h.startswith(tok) for h in haystack)


def match_score(wanted: list[str], text: str | None) -> float:
    """Share of the wanted tokens that occur in `text` (0.0 - 1.0)."""
    wanted = list(dict.fromkeys(wanted))
    if not wanted:
        return 0.0
    hay = set(tokens(text))
    return sum(_token_found(w, hay) for w in wanted) / len(wanted)


def keywords_ok(keywords: list[str], text: str | None) -> bool:
    """Every keyword (each may be several words) must be fully present."""
    hay = set(tokens(text))
    return all(all(_token_found(w, hay) for w in tokens(k)) for k in keywords)


def required_tokens(target: dict) -> list[str]:
    """Words a candidate URL must contain in full: the listing keyword
    (`match`, e.g. "SE 3") and the `keywords` - otherwise "Apple Watch SE 3"
    would accept any Apple Watch wristband (2 of 4 words)."""
    toks = tokens(target.get("match"))
    for k in target.get("keywords") or []:
        toks += tokens(k)
    return list(dict.fromkeys(toks))


def wanted_tokens(target: dict) -> list[str]:
    toks = tokens(target["product"])
    for k in target.get("keywords") or []:
        toks += tokens(k)
    return list(dict.fromkeys(toks))


# Thresholds (share of product-name words that must match)
CANDIDATE_MIN_URL_SCORE = 0.5    # sitemap URL path, to be worth opening
ACCEPT_MIN_NAME_SCORE = 0.6      # product name/title of an opened candidate
MISMATCH_MAX_NAME_SCORE = 0.4    # stored URL counts as "wrong product" below this


def name_score(target: dict, name: str | None, title: str | None) -> float:
    return match_score(wanted_tokens(target), f"{name or ''} {title or ''}")


def page_matches(target: dict, name: str | None, title: str | None) -> bool:
    text = f"{name or ''} {title or ''}"
    return name_score(target, name, title) >= ACCEPT_MIN_NAME_SCORE and keywords_ok(
        target.get("keywords") or [], text)


# --------------------------------------------------------------------------
# Sitemaps
# --------------------------------------------------------------------------

_LOC = re.compile(rb"<(?:\w+:)?loc>\s*(?:<!\[CDATA\[)?\s*(.*?)\s*(?:\]\]>)?\s*</(?:\w+:)?loc>", re.S | re.I)


def parse_sitemap(body: bytes) -> tuple[bool, list[str]]:
    """Returns (is_index, urls). Handles gzip and plain XML."""
    if body[:2] == b"\x1f\x8b":
        body = gzip.decompress(body)
    is_index = b"<sitemapindex" in body[:2000].lower() or b":sitemapindex" in body[:2000].lower()
    urls = []
    for m in _LOC.finditer(body):
        u = m.group(1).decode("utf-8", errors="replace").strip().replace("&amp;", "&")
        if u.startswith(("http://", "https://")):
            urls.append(u)
    return is_index, urls


_GOOD_SITEMAP = re.compile(r"produ|artikel|article|item|pdp|offer|angebot|catalog", re.I)
_BAD_SITEMAP = re.compile(
    r"image|video|blog|news|magazin|ratgeber|content|cms|store|filiale|markt|brand|marke|"
    r"categor|kategor|landing|static|page|tag|faq|hilfe|help|service|job|karriere", re.I)


def _sitemap_name(u: str) -> str:
    # "sitemap" itself contains "item" - remove it before classifying
    return urlsplit(u).path.lower().replace("sitemap", " ")


def rank_sitemaps(urls: list[str], target: dict | None = None) -> list[str]:
    """Sitemaps whose name matches the product first (e.g. ".../apple.xml"),
    then product sitemaps; obviously irrelevant ones (images, blog, stores,
    ...) dropped."""
    def good(u: str) -> bool:
        return bool(_GOOD_SITEMAP.search(_sitemap_name(u)))

    wanted = [w for w in wanted_tokens(target) if not w.isdigit()] if target else []

    def key(u: str):
        name_hit = match_score(wanted, _sitemap_name(u)) if wanted else 0.0
        return (-name_hit, 0 if good(u) else 1, u)

    kept = [u for u in urls if good(u) or not _BAD_SITEMAP.search(_sitemap_name(u))]
    return sorted(dict.fromkeys(kept), key=key)


def score_urls(urls, target: dict, top: int = 5, exclude: set[str] | None = None) -> list[tuple[float, str]]:
    """Best `top` URLs by how well their path matches the product name."""
    wanted = wanted_tokens(target)
    required = required_tokens(target)
    exclude = exclude or set()
    best: list[tuple[float, int, str]] = []
    for u in urls:
        if u in exclude:
            continue
        path = urlsplit(u).path
        s = match_score(wanted, path)
        if s < CANDIDATE_MIN_URL_SCORE:
            continue
        if required and match_score(required, path) < 1.0:
            continue
        # shorter paths win ties (fewer accessories / bundles)
        item = (s, -len(path), u)
        if len(best) < top:
            heapq.heappush(best, item)
        elif item > best[0]:
            heapq.heapreplace(best, item)
    return [(s, u) for s, _, u in sorted(best, reverse=True)]


# --------------------------------------------------------------------------
# Network part
# --------------------------------------------------------------------------

MAX_SITEMAP_FILES = 20
MAX_SITEMAP_BYTES = 60 * 1024 * 1024
MAX_CANDIDATES = 3


async def collect_candidates(fetcher, origin: str, target: dict, exclude: set[str]) -> tuple[list[str], str]:
    """Walk the shop's sitemaps and return up to MAX_CANDIDATES product URLs
    (best first) plus a short note on what was searched."""
    rules = await fetcher.robots_for(origin + "/")
    queue = list(rules.sitemaps) or [origin + "/sitemap.xml"]
    queue = rank_sitemaps(queue, target) or queue
    seen: set[str] = set()
    pool: dict[str, float] = {}
    files = 0
    total = 0
    cache = fetcher.__dict__.setdefault("sitemap_cache", {})   # per run: url -> parsed sitemap
    while queue and files < MAX_SITEMAP_FILES and total < MAX_SITEMAP_BYTES:
        url = queue.pop(0)
        if url in seen:
            continue
        seen.add(url)
        files += 1
        if url not in cache:
            body = await fetcher.get_bytes(url)
            parsed = None
            if body is not None:
                try:
                    parsed = parse_sitemap(body)
                except Exception:
                    parsed = None
                total += len(body)
            cache[url] = parsed
        if cache[url] is None:
            continue
        is_index, locs = cache[url]
        if is_index:
            queue = rank_sitemaps([u for u in locs if u not in seen] + queue, target)
            continue
        for s, u in score_urls(locs, target, top=10, exclude=exclude):
            pool[u] = max(pool.get(u, 0.0), s)
        # enough perfect hits -> stop early, save requests
        if sum(1 for s in pool.values() if s >= 0.999) >= MAX_CANDIDATES:
            break
    ranked = score_urls(pool.keys(), target, top=MAX_CANDIDATES)
    note = f"{files} sitemap file(s) searched, {len(pool)} candidate(s)"
    return [u for _, u in ranked], note
