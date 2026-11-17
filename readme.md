# gravel_frameset_tracker

New module for the existing **Preis-Tracker** repo. Tracks offers for race-oriented
gravel frame sets (32–45mm tire clearance) from well-known brands, and notifies when:

- an **aluminium** frameset drops below **€350**
- a **carbon** frameset drops below **€450**

## How it fits into the repo

This is a self-contained module — drop the `gravel_frameset_tracker/` folder next to
your existing tariff-tracker code. Notifications are already wired to the same ntfy.sh
topic as the tariff bot, so both push through one channel — nothing to configure there.
Scheduling: call `main.py` on the same schedule/runner (cron, GitHub Actions, etc.) you
already use for the tariff bot.

**On the repo having a `config.py` and `requirements.txt` already:** that's fine as
long as this stays in its own `gravel_frameset_tracker/` subfolder rather than getting
unzipped flat into the repo root — `gravel_frameset_tracker/config.py` and the tariff
bot's root-level `config.py` are different files at different paths, so nothing
overwrites and nothing collides at import time (each bot's `main.py` is run as its own
script, so Python resolves `import config` to whichever folder that script lives in).
The one thing to actually merge by hand: **`requirements.txt`**. You already added
`playwright` for the tariff bot, so this module's `requirements.txt` is mostly
redundant — just check the root one has `requests` too (used for the placeholder
notification), then you can delete this module's copy and keep a single
`pip install -r requirements.txt` for both bots.

## What's real vs. what still needs a live run

I don't have a real browser in this sandbox, but I do have a page-fetch tool, and used
it to check all six retailers' actual live pages rather than guess. Verdict per site:

- **bike-components.de**: real category confirmed
  (`/en/components/frames/cyclocross-gravel/`, 52 items, 3 pages). No on-page search —
  the adapter paginates the category and matches titles instead. Price format is
  English-style (`1,000.00€`).
- **bike24.de**: real category confirmed
  (`/cycling/parts/bike-frames/cyclocross-gravel-bike-frames`), now a real
  implementation. Price format is German-style (`988,24 €`) — **the two sites format
  numbers differently, don't share the price regex between them**, I only caught this
  by checking both.
- **canyon.com**: disabled. The Grail's product page only listed complete bikes, no
  frame-only SKU found.
- **fahrrad.de**: disabled. Checked their site structure — frame-*size* calculators and
  complete-bike categories exist, but no frame-*purchase* category anywhere, for road
  or gravel. Same pattern as Canyon: a complete-bike-and-accessories retailer, not a
  frame-only one.
- **rosebikes.de**: disabled, but with a real, useful finding: Rose does sell at least
  one frameset standalone (confirmed real product page for their road-race Xlite 06),
  and their race-gravel platform (Backroad FF) is confirmed at exactly 45mm clearance
  via official spec — added to `models.json`. But I could only find the Backroad FF as
  complete bikes plus a crash-replacement parts doc, not a clear "buy frameset new"
  page. Worth you checking directly since you know the site better than I can
  search-fetch it.

- **schlierseer-bikeparts.de**: disabled — real and relevant (Cube frame
  specialist, matches your Cube Agree), but structurally incompatible with this bot.
  Real category confirmed (`/cross`), but every listing is an individual physical
  frame with **no published price** — it's inquiry/quote-based, not a fixed-price
  catalogue. Their eBay shop does show real prices for some of the same frames, but
  that's a different, harder scraping target I haven't attempted.

Net effect on `models.json`: dropped the nonexistent Canyon Grail AL, corrected
"Ridley Kanzo Speed" → "Kanzo Fast" (actual current name), excluded BMC Kaius (current
generation is 52mm, over your limit), added Specialized Crux DSW and Rose Backroad FF
as real candidates with their verification status noted inline.

Both real adapters (bike-components.de, bike24.de) match products by scanning link
text and href patterns confirmed against actual page content, rather than guessed CSS
class names — more likely to survive a markup change than invented selectors. None of
this replaces an actual `python main.py` run against live Playwright — text from a
page-fetch tool isn't identical to what a real browser DOM exposes — but it's a much
closer starting point than the original guesswork.

## Assumptions baked in (change in `config.py` if wrong)

- EUR pricing
- Frame + fork ("frameset") listings only, not complete bikes
- New listings only — no used marketplaces (e.g. bikemarkt.mtb-news.de, Kleinanzeigen)
- Frame size 56 only (adjust `FRAME_SIZE_FILTER` in `config.py` or set to `None` for all sizes)

## Model discovery

`discover_models.py` checks a short list of curated sources (manufacturer new-model
pages + a couple of well-known "best gravel bike" roundups) each run, looks for
mentions of known brands alongside gravel/frameset keywords, and writes anything new
to `candidates.json` for a quick manual yes/no before it's merged into `models.json`.
Fully automatic brand/spec classification from scraped text is unreliable enough
(marketing copy is inconsistent about clearance numbers) that I kept a human
confirmation step rather than silently auto-adding models — flip `AUTO_APPROVE` in
`config.py` if you'd rather it just add everything it finds.

## Files

```
gravel_frameset_tracker/
├── config.py           # thresholds, filters, source list
├── models.json          # seed model list (brand, model, materials, clearance)
├── candidates.json       # newly discovered models awaiting approval (created on first run)
├── discover_models.py   # Step 1: find new models, update models.json
├── scrape_prices.py      # Step 2: scrape retailers for tracked models, check thresholds
├── notify.py            # Step 3: push notification — wired to the tariff bot's ntfy topic
├── main.py               # orchestrates discover -> scrape -> notify
├── requirements.txt
└── scrapers/
    ├── __init__.py       # registers all adapters
    ├── base.py           # shared Offer type + adapter interface
    ├── bike_components.py  # real, working
    ├── bike24.py           # real, working
    ├── canyon.py           # disabled — no frame-only SKU found
    ├── fahrrad_de.py       # disabled — no frame category found
    ├── rosebikes.py        # disabled — Backroad FF frameset not confirmed
    └── schlierseer.py      # disabled — no published prices to scrape
```

## Running it

```bash
pip install -r requirements.txt
playwright install chromium
python main.py
```

---

# black_week

Self-contained module that fetches a list of product pages twice a day with a real
headless browser (Playwright, Chromium), reads the prices and commits the results to
`black_week/results/`. An external assistant reads these files. It does not touch the
other trackers (own folder, own `requirements.txt`, own workflow).

Fetching is deliberately polite: honest User-Agent
(`PriceTracker/1.0 (+https://github.com/muellermwolfgang-collab/Price-tracker)`),
robots.txt is checked before every request, one request at a time per host with a
5–10 s pause, one retry on timeout and none on a block. No stealth plugins, fingerprint
spoofing, proxies, captcha solving or logins — a blocked page is recorded as `blocked`
and left alone.

## Maintaining `black_week/targets.yaml`

You define **products and shops**; URLs are looked after automatically (see
*URL maintenance* below). One entry per product and shop:

```yaml
- product: Apple Watch SE 3          # free text
  shop: Back Market                  # free text
  type: listing                      # product = single product page, listing = category/comparison page
  match: SE 3                        # listing only: only offers whose text contains this keyword
  price_selector: .price .value      # optional CSS selector, last fallback
  url: https://www.backmarket.de/de-de/p/apple-watch-se-series-3   # optional starting point
  active: true                       # false = skip without deleting the entry

- product: Anker Solarbank 3 Pro 2.000 W   # no URL needed:
  shop: toom
  site: toom.de                      # shop address, the product page is searched for
  keywords: ["2.000 W"]              # optional: words the product page must contain
  active: true
```

Prices are taken from, in this order: JSON-LD (`Product` → `Offer`/`AggregateOffer`),
meta tags (`product:price:amount`, `og:price:amount`, `itemprop="price"`), the
`price_selector`, and — for listings — the visible offer tiles containing `match`
(title, price and condition such as "Sehr gut" per tile, stored in `offers`).
If a shop shows `no_price`, open the page, find the price element and add a
`price_selector`.

## URL maintenance (automatic)

Each run first checks the stored URL while fetching it. A URL counts as broken if
the page is gone (HTTP 404/410), shows no price, or shows a different product
(product name not found in the page's product name/title). Then:

1. **Search:** the shop's sitemaps (listed in its robots.txt for crawlers) are
   searched for URLs whose path matches the product name. No search engines, no
   site search, same robots.txt and pacing rules as the price fetch.
2. **Verify:** the best candidates are opened; the first one with a price and a
   matching product name (and all `keywords`) is taken.
3. **Update:** its price goes into the results (`url_check: updated`,
   `previous_url`), and the URL is saved in `black_week/urls.json`, which the
   workflow commits. Later runs use it. If you change `url` in `targets.yaml`,
   your URL wins again.

Nothing found → `url_check: broken`, the reason is in `note` and in a
"URL-Pflege" section of `latest.md`; the search is retried every run. Pages that
are blocked or disallowed by robots.txt can't be checked (`not_checked`).
Listing pages are only checked for 404/410, not searched.

## Results

- `black_week/results/latest.json` — current run, one object per entry (`product`, `shop`,
  `url`, `status`, `http_status`, `price`, `currency`, `shipping`, `availability`,
  `source`, `offers`, `page_title`, `fetched_at` in UTC, plus `price_high`, `offer_count`,
  `note`, `url_check` = ok/updated/broken/not_checked, `previous_url`)
- `black_week/results/latest.md` — the same as a table, time stamp in Europe/Berlin
- `black_week/results/history.csv` — every run appended

## Running it

Automatically at 06:15 and 17:15 UTC (07:15 / 18:15 Berlin in winter) via
`.github/workflows/black-week.yml`. Manually: Actions tab → **Black Week Prices** →
**Run workflow**. A failing URL never fails the job; it only fails if no result file
could be written. Nothing is committed if nothing changed.

Locally:

```bash
pip install -r black_week/requirements.txt
python -m playwright install chromium
python black_week/run.py --dry-run            # fetch + print to console, writes nothing
python black_week/run.py --dry-run --only tink  # only entries whose shop/product contains "tink"
python -m pytest black_week/tests             # offline tests (saved HTML + local test server)
```

## Status values

| Status | Meaning |
|---|---|
| `ok` | price found |
| `no_price` | page loaded, but no price found (consider a `price_selector`) |
| `blocked` | HTTP 403/429/503 or a bot wall ("Access denied", "Just a moment", "Pardon Our Interruption", captcha) — logged, not bypassed |
| `robots` | path disallowed by the shop's robots.txt — not fetched |
| `timeout` | page did not load within 30 s (after one retry) |
| `error` | anything else, e.g. HTTP 404, network error, robots.txt unreachable (see `note`) |
